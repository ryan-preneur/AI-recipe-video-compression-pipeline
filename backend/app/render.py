import base64, os
from pathlib import Path
from .gemini import generate
from .media import run, probe, PipelineError
from .models import Draft, LANGUAGES
from .store import ROOT

def duration(path): return float(probe(path)['format']['duration'])

def stamp(s):
    ms=round(s*1000); h,ms=divmod(ms,3600000); m,ms=divmod(ms,60000); sec,ms=divmod(ms,1000)
    return f'{h:02}:{m:02}:{sec:02},{ms:03}'

def subtitle_files(folder,lines):
    srt=[];vtt=['WEBVTT','']
    for i,(a,b,t) in enumerate(lines,1):
        safe=t.replace('\n',' ').strip()
        srt += [str(i),f'{stamp(a)} --> {stamp(b)}',safe,'']
        vtt += [f'{stamp(a).replace(",", ".")} --> {stamp(b).replace(",", ".")}',safe,'']
    (folder/'captions.srt').write_text('\n'.join(srt),encoding='utf-8')
    (folder/'captions.vtt').write_text('\n'.join(vtt),encoding='utf-8')

def render(job, draft: Draft, progress=lambda x:None, speed=1.0):
    if not os.getenv('GEMINI_API_KEY'):
        raise PipelineError('GEMINI_API_KEY is required to render narration')
    folder=ROOT/job['id']; source=folder/job['metadata']['source_file']
    if not source.exists(): raise PipelineError('Source media is missing; create the job again')
    language=job['output_language']
    clips=[]; subtitles=[]; offset=0
    for i,cut in enumerate(draft.cuts):
        progress(f'Narrating and rendering clip {i+1} of {len(draft.cuts)}')
        speech=folder/f'voice_{i:03}.wav'
        parts=generate(os.getenv('GEMINI_TTS_MODEL','gemini-3.8-flash-tts'),
            [{'text':cut.narration_text}],
            {'responseModalities':['AUDIO'],'speechConfig':{'voiceConfig':{'voice':'Kore'}}})
        try:
            speech.write_bytes(base64.b64decode(next(part['inlineData']['data'] for part in parts if 'inlineData' in part)))
        except (KeyError, StopIteration, ValueError) as exc:
            raise PipelineError('Gemini narration returned no audio; retry generation') from exc
        voice_length=duration(speech)
        visual=cut.source_end-cut.source_start
        visual_output=visual/speed
        if voice_length > visual_output+9:
            raise PipelineError(f'Clip {i+1} narration is too long. Shorten its text or extend its source range.')
        total=max(visual_output,voice_length+.4)
        if offset+total > job['duration']+5:
            raise PipelineError(f'Narration exceeds the {job["duration"]} second target. Shorten the script or cuts before rendering.')
        extra=max(0,total-visual_output)
        clip=folder/f'clip_{i:03}.mp4'
        vf=(f'[0:v]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1,'
            f'setpts=(PTS-STARTPTS)/{speed:.3f},tpad=stop_mode=clone:stop_duration={extra:.3f},trim=duration={total:.3f},setpts=PTS-STARTPTS[v];'
            f'[1:a]adelay=200,apad,atrim=duration={total:.3f},asetpts=PTS-STARTPTS[a]')
        run(['ffmpeg','-y','-ss',str(cut.source_start),'-t',str(visual),'-i',str(source),'-i',str(speech),
             '-filter_complex',vf,'-map','[v]','-map','[a]','-r','30','-c:v','libx264','-preset','veryfast','-crf','23',
             '-pix_fmt','yuv420p','-c:a','aac','-b:a','128k','-movflags','+faststart',str(clip)],300)
        actual=duration(clip); clips.append(clip)
        subtitles.append((offset+.1,offset+actual-.1,cut.narration_text)); offset+=actual
    concat=folder/'concat.txt'
    concat.write_text(''.join(f"file '{p.name}'\n" for p in clips),encoding='utf-8')
    joined=folder/'joined.mp4'
    run(['ffmpeg','-y','-f','concat','-safe','0','-i',str(concat),'-c','copy',str(joined)],300)
    subtitle_files(folder,subtitles)
    progress('Muxing captions and checking output')
    output=folder/'recipe_reel.mp4'
    run(['ffmpeg','-y','-i',str(joined),'-i',str(folder/'captions.srt'),'-map','0:v:0','-map','0:a:0','-map','1:s:0',
         '-c:v','copy','-c:a','copy','-c:s','mov_text','-metadata:s:s:0',f'language={language}',
         '-movflags','+faststart',str(output)],300)
    info=probe(output)
    if not output.exists() or output.stat().st_size<1024 or float(info['format']['duration'])<1:
        raise PipelineError('The rendered MP4 failed validation')
    return output,float(info['format']['duration'])
