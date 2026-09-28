import os, threading, math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from dotenv import load_dotenv
from .models import CreateJob, Draft, DraftUpdate, RenderRequest, LANGUAGES
from .media import validate_youtube, ingest, probe, PipelineError
from .intelligence import get_transcript, plan
from .render import render
from . import store

load_dotenv()
app=FastAPI(title='Recipe Reel API')
app.add_middleware(
    CORSMiddleware,
    allow_origins=[x.strip() for x in os.getenv('CORS_ORIGINS','').split(',') if x.strip()],
    allow_origin_regex=r'https?://(localhost|127\.0\.0\.1):\d+',
    allow_methods=['GET','POST','PUT'],
    allow_headers=['*'],
)
executor=ThreadPoolExecutor(max_workers=2)
active=set(); guard=threading.Lock()
store.cleanup_expired(int(os.getenv('RETENTION_DAYS','7')))

def need(job_id):
    job=store.get(job_id)
    if not job: raise HTTPException(404,'Job not found')
    return job

def run_analysis(job_id, source_hint='auto'):
    try:
        job=need(job_id);store.update(job_id,state='processing',stage='Downloading video')
        folder=store.ROOT/job_id
        meta=job.get('metadata')
        source=folder/meta['source_file'] if meta and meta.get('source_file') else None
        if not source or not source.exists():
            existing=next((p for p in folder.glob('source.*') if p.suffix.lower() in {'.mp4','.webm','.mkv'}),None)
            if existing:
                source=existing
                meta={'title':'Recipe video','duration':float(probe(source)['format']['duration']),
                      'source_file':source.name,'source_language':source_hint if source_hint!='auto' else '',
                      'caption_warning':'Captions were rate limited; source audio will be transcribed instead.'}
            else:
                source,meta=ingest(job_id,job['url'],source_hint)
        store.update(job_id,metadata=meta,stage='Getting transcript')
        preferred=source_hint if source_hint!='auto' else meta.get('source_language')
        transcript,lang,rough=get_transcript(job_id,source,meta['duration'],preferred)
        meta['usage']={'source_minutes':round(meta['duration']/60,2),'transcription_chunks':math.ceil(meta['duration']/20) if rough else 0,'transcript_segments':len(transcript)}
        store.update(job_id,metadata=meta)
        store.update(job_id,stage='Planning recipe cuts')
        current=need(job_id)
        draft=plan(current,transcript,lang,rough)
        store.update(job_id,state='review',stage='Review the proposed cuts',draft=draft.model_dump(),error=None)
    except Exception as exc:
        store.update(job_id,state='failed',stage='Analysis failed',error=str(exc)[:900])
    finally:
        with guard: active.discard(job_id)

def run_render(job_id, speed=1.0):
    try:
        job=need(job_id); draft=Draft.model_validate(job['draft'])
        store.update(job_id,state='rendering',stage='Starting render',error=None)
        output,seconds=render(job,draft,lambda stage:store.update(job_id,stage=stage),speed=speed)
        meta=job['metadata'];meta['output_duration']=seconds;meta['playback_speed']=speed
        meta.setdefault('usage',{})['voice_characters']=sum(len(c.narration_text) for c in draft.cuts)
        store.update(job_id,state='done',stage='Ready to download',metadata=meta,output=str(output))
    except Exception as exc:
        store.update(job_id,state='review',stage='Render failed',error=str(exc)[:900])
    finally:
        with guard: active.discard(job_id)

def run_replan(job_id):
    try:
        job=need(job_id)
        old=Draft.model_validate(job['draft'])
        store.update(job_id,state='processing',stage='Replanning from corrected transcript',error=None)
        revised=plan(job,old.transcript,old.source_language,any(s.uncertain for s in old.transcript))
        store.update(job_id,state='review',stage='Review the revised cuts',draft=revised.model_dump())
    except Exception as exc:
        store.update(job_id,state='review',stage='Replanning failed',error=str(exc)[:900])
    finally:
        with guard: active.discard(job_id)

@app.get('/health')
def health(): return {'ok':True,'languages':{x:y[0] for x,y in LANGUAGES.items()}}

@app.post('/jobs',status_code=202)
def create_job(request:CreateJob):
    try: url=validate_youtube(request.url)
    except PipelineError as e: raise HTTPException(400,str(e))
    if not os.getenv('GEMINI_API_KEY'):
        raise HTTPException(503,'Set GEMINI_API_KEY in backend/.env and restart the backend before analyzing a recipe')
    job_id=store.create(url,request.duration,request.output_language)
    with guard: active.add(job_id)
    executor.submit(run_analysis,job_id,request.source_language)
    return {'id':job_id}

@app.post('/jobs/{job_id}/retry',status_code=202)
def retry_job(job_id:str):
    job=need(job_id)
    if job['state']!='failed': raise HTTPException(409,'Only failed analysis can be retried')
    with guard:
        if job_id in active: raise HTTPException(409,'Job is already running')
        active.add(job_id)
    executor.submit(run_analysis,job_id,'auto')
    return {'id':job_id,'state':'processing'}

@app.get('/jobs/{job_id}')
def get_job(job_id:str):
    job=need(job_id)
    return {k:job[k] for k in ['id','url','duration','output_language','state','stage','error','metadata','created_at','updated_at']}

@app.get('/jobs/{job_id}/draft',response_model=Draft)
def get_draft(job_id:str):
    job=need(job_id)
    if not job['draft']: raise HTTPException(409,'Draft is not ready')
    return job['draft']

@app.put('/jobs/{job_id}/draft',response_model=Draft)
def save_draft(job_id:str,body:DraftUpdate):
    job=need(job_id)
    if job['state'] not in {'review','done'} or not job['draft']: raise HTTPException(409,'Job is not ready for editing')
    if not body.cuts: raise HTTPException(422,'Keep at least one cut')
    duration=job['metadata']['duration']; seen=set()
    for cut in body.cuts:
        if cut.source_end>duration+.1: raise HTTPException(422,'A cut extends beyond the source video')
        if cut.id in seen: raise HTTPException(422,'Cut IDs must be unique')
        seen.add(cut.id)
    old=Draft.model_validate(job['draft'])
    new=old.model_copy(update={'source_language':body.source_language,'transcript':body.transcript,'cuts':body.cuts})
    store.update(job_id,state='review',draft=new.model_dump(),output=None,error=None)
    return new

@app.post('/jobs/{job_id}/replan',status_code=202)
def start_replan(job_id:str):
    job=need(job_id)
    if job['state']!='review' or not job['draft']: raise HTTPException(409,'Save a corrected transcript first')
    with guard:
        if job_id in active: raise HTTPException(409,'Job is already running')
        active.add(job_id)
    executor.submit(run_replan,job_id)
    return {'id':job_id,'state':'processing'}

@app.post('/jobs/{job_id}/render',status_code=202)
def start_render(job_id:str, body:RenderRequest):
    job=need(job_id)
    if job['state']!='review' or not job['draft']: raise HTTPException(409,'Review a draft before rendering')
    with guard:
        if job_id in active: raise HTTPException(409,'Job is already running')
        active.add(job_id)
    executor.submit(run_render,job_id,body.speed)
    return {'id':job_id,'state':'rendering'}

@app.get('/jobs/{job_id}/source')
def source(job_id:str):
    job=need(job_id)
    if not job['metadata']: raise HTTPException(409,'Source is not ready')
    path=store.ROOT/job_id/job['metadata']['source_file']
    if not path.exists(): raise HTTPException(404,'Source unavailable')
    media_type={'mp4':'video/mp4','webm':'video/webm','mkv':'video/x-matroska'}.get(path.suffix.lstrip('.'),'application/octet-stream')
    return FileResponse(path,media_type=media_type)

@app.get('/jobs/{job_id}/output')
def output(job_id:str):
    job=need(job_id)
    if job['state']!='done' or not job['output']: raise HTTPException(409,'Output is not ready')
    path=Path(job['output'])
    if not path.exists(): raise HTTPException(404,'Output missing')
    return FileResponse(path,media_type='video/mp4',filename='recipe_reel.mp4')

@app.get('/jobs/{job_id}/captions')
def captions(job_id:str):
    job=need(job_id)
    if job['state']!='done': raise HTTPException(409,'Captions are not ready')
    path=store.ROOT/job_id/'captions.vtt'
    return FileResponse(path,media_type='text/vtt')
