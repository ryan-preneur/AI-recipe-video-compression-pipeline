import base64, json, os, re, uuid
from pathlib import Path
import webvtt
from .gemini import generate, text as gemini_text
from .media import run, PipelineError
from .models import Cut, Draft, Segment, LANGUAGES
from .store import ROOT

CODES = {"en":"en","hi":"hi","ta":"ta","bn":"bn","kn":"kn"}

def vtt_seconds(value):
    a=value.replace(',', '.').split(':')
    return int(a[0])*3600+int(a[1])*60+float(a[2])

def captions(folder, preferred=None):
    files=list(folder.glob('source.*.vtt'))
    def rank(p):
        m=re.search(r'source\.([a-z]{2})',p.name)
        lang=m.group(1) if m else None
        return (lang != preferred, lang not in CODES, p.name)
    for path in sorted(files,key=rank):
        lang=(re.search(r'source\.([a-z]{2})',path.name) or [None,None])[1]
        if lang not in CODES: continue
        try:
            parsed=[]; previous=''
            for cue in webvtt.read(str(path)):
                raw=re.sub(r'<[^>]+>','',cue.text)
                raw=re.sub(r'\s+',' ',raw).strip()
                if not raw or raw==previous: continue
                start,end=vtt_seconds(cue.start),vtt_seconds(cue.end)
                if end>start: parsed.append(Segment(start=start,end=end,text=raw))
                previous=raw
            if len(parsed)>=5: return parsed,lang,False
        except Exception: continue
    return None,None,False

def transcribe_chunks(audio, duration, folder):
    if not os.getenv('GEMINI_API_KEY'): raise PipelineError('GEMINI_API_KEY is required when the video has no usable source captions')
    chunks=[]; detected=None
    for start in range(0,int(duration)+1,20):
        if start>=duration: break
        length=min(20,duration-start)
        path=folder/f'chunk_{start}.mp3'
        run(['ffmpeg','-y','-ss',str(start),'-t',str(length),'-i',str(audio),'-ac','1','-b:a','48k',str(path)],90)
        try:
            parts=generate(os.getenv('GEMINI_MODEL','gemini-3.8-flash'),[
                {'text':'Transcribe the speech in this audio exactly in its original language. Return only the transcript text. If there is no speech, return an empty string.'},
                {'inlineData':{'mimeType':'audio/mpeg','data':base64.b64encode(path.read_bytes()).decode('ascii')}}])
            spoken=gemini_text(parts)
            if spoken: chunks.append(Segment(start=float(start),end=float(start+length),text=spoken,uncertain=True))
        finally:
            path.unlink(missing_ok=True)
    if not chunks: raise PipelineError('No speech could be transcribed')
    return chunks, detected if detected in CODES else None, True

def get_transcript(job_id, source, duration, preferred=None):
    folder=ROOT/job_id
    segments,lang,uncertain=captions(folder,preferred)
    if segments: return segments,lang,uncertain
    audio=folder/'source_audio.mp3'
    run(['ffmpeg','-y','-i',str(source),'-vn','-ac','1','-b:a','48k',str(audio)],300)
    return transcribe_chunks(audio,duration,folder)

def ask_json(instructions, content, model=None):
    parts=generate(model or os.getenv('GEMINI_MODEL','gemini-3.8-flash'),[{'text':instructions+'\n\n'+content}],{'responseMimeType':'application/json'})
    try: return json.loads(gemini_text(parts))
    except Exception as e: raise PipelineError('The recipe planner returned invalid data; retry analysis') from e

def plan(job, transcript, source_language, rough_times):
    if not os.getenv('GEMINI_API_KEY'): raise PipelineError('GEMINI_API_KEY is required for recipe planning')
    lang=LANGUAGES[job['output_language']][0]
    items=[s.model_dump() for s in transcript]
    # Keep the source text and timestamps together. For long videos, split later; cap V1 input.
    payload=json.dumps({'target_seconds':job['duration'],'output_language':lang,'source_language':source_language or 'unknown','segments':items},ensure_ascii=False)
    instructions=('You plan a short, usable cooking tutorial from a timestamped transcript. Return ONLY a JSON object with keys dish, source_language, cuts, warnings. '
      'Each cut has source_start, source_end, purpose, source_evidence, narration_text, uncertain. Keep chronological source order. '
      'Use only evidence in the supplied transcript; never invent amounts, heat, timings, visuals, or ingredients. '
      'Choose enough distinct actions to cover ingredients/amounts, preparation, cooking, doneness if stated, and final dish if stated. '
      'Exclude intros, sponsors and repeated talking. Target the duration but prioritize necessary steps. '
      'Use concise natural narration in the requested output language. source_evidence must quote or paraphrase the matched transcript. '
      'Each cut must be 2 to 20 seconds and inside a segment time range; uncertain=true for ambiguous, coarse, or visual-only evidence. '
      'If a crucial step cannot fit, state this in warnings. There is no requirement to claim visual proof from text alone.')
    data=ask_json(instructions,payload)
    cuts=[]; source_duration=job['metadata']['duration']; prior=-1
    for raw in data.get('cuts',[]):
        try:
            cut=Cut(id=uuid.uuid4().hex[:8],**{k:raw[k] for k in ('source_start','source_end','purpose','source_evidence','narration_text','uncertain')})
        except Exception: continue
        if cut.source_end>source_duration+.1 or cut.source_start<prior: continue
        if not any(s.start-1<=cut.source_start<=s.end+1 for s in transcript): continue
        prior=cut.source_start; cuts.append(cut)
    if not cuts: raise PipelineError('Could not create grounded clips; edit the transcript and retry')
    warnings=[str(x) for x in data.get('warnings',[])][:8]
    if job['metadata'].get('caption_warning'):
        warnings.append(job['metadata']['caption_warning'])
    if rough_times: warnings.append('Speech fallback gives coarse 20-second transcript blocks. Review and adjust every proposed cut against the video.')
    if sum(x.source_end-x.source_start for x in cuts)>job['duration']*1.25: warnings.append('The suggested cuts exceed the target; shorten or remove nonessential clips before rendering.')
    return Draft(dish=str(data.get('dish') or job['metadata']['title'])[:120],source_language=source_language or str(data.get('source_language') or 'unknown'),output_language=job['output_language'],transcript=transcript,cuts=cuts,warnings=warnings)
