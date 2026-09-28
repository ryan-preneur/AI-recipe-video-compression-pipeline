import json, os, re, subprocess, sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from .store import ROOT

class PipelineError(Exception): pass

def validate_youtube(url):
    try: p=urlparse(url)
    except ValueError: raise PipelineError("Invalid URL")
    host=(p.hostname or "").lower()
    if p.scheme != "https" or host not in {"youtube.com","www.youtube.com","m.youtube.com","youtu.be"}:
        raise PipelineError("Enter a public HTTPS YouTube URL")
    if host == "youtu.be": vid=p.path.strip("/")
    elif p.path == "/watch": vid=parse_qs(p.query).get("v",[""])[0]
    elif p.path.startswith("/shorts/"): vid=p.path.split("/")[2]
    else: raise PipelineError("Use a YouTube watch or Shorts link")
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}",vid): raise PipelineError("Invalid YouTube video ID")
    return "https://www.youtube.com/watch?v="+vid

def run(args, timeout=600):
    if args[0] == 'yt-dlp':
        args = [sys.executable, '-m', 'yt_dlp', *args[1:]]
    try:
        p=subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError: raise PipelineError(f"Missing tool: {args[0]}")
    except subprocess.TimeoutExpired: raise PipelineError("Processing timed out")
    if p.returncode: raise PipelineError((p.stderr or p.stdout)[-700:] or f"{args[0]} failed")
    return p.stdout

def probe(path):
    return json.loads(run(["ffprobe","-v","error","-show_entries","format=duration:stream=codec_type,width,height","-of","json",str(path)], 60))

def _caption_language(info, preferred):
    languages=("en","hi","ta","bn","kn")
    if preferred in languages:
        return preferred
    original=(info.get('language') or '').split('-')[0]
    if original in languages:
        return original
    manual=info.get('subtitles') or {}
    return next((code for code in languages if code in manual), None)

def ingest(job_id,url, preferred=None):
    folder=ROOT/job_id
    info=json.loads(run(["yt-dlp","--no-playlist","--dump-single-json","--skip-download",url], 60))
    seconds=float(info.get("duration") or 0)
    if not seconds or seconds > int(os.getenv("MAX_SOURCE_MINUTES","30"))*60: raise PipelineError("Video is unavailable or exceeds the source duration limit")
    cap_mb=int(os.getenv("MAX_DOWNLOAD_MB","600"))
    run(["yt-dlp","--no-playlist","--max-filesize",f"{cap_mb}M","-f","bv*[height<=1080]+ba/b[height<=1080]/best","--merge-output-format","mp4","-o",str(folder/"source.%(ext)s"),url],900)
    candidates=[x for x in folder.glob("source.*") if x.suffix.lower() in {".mp4",".webm",".mkv"}]
    if not candidates: raise PipelineError("The source video could not be obtained; check availability and permissions")
    source=candidates[0]
    if source.stat().st_size > cap_mb*1024*1024: raise PipelineError("Downloaded file exceeds size limit")
    meta={"title":info.get("title","Untitled recipe"),"duration":seconds,"thumbnail":info.get("thumbnail"),"source_file":source.name,"video_id":info.get("id"),"source_language":(info.get("language") or "")[:2]}
    language=_caption_language(info,preferred)
    if language:
        try:
            run(["yt-dlp","--no-playlist","--skip-download","--write-subs","--write-auto-subs","--sub-langs",language,"--sub-format","vtt/best","-o",str(folder/"source.%(ext)s"),url],90)
        except PipelineError:
            meta['caption_warning']='Captions were unavailable or rate limited; source audio will be transcribed instead.'
    return source,meta

def extract_audio(source, out):
    run(["ffmpeg","-y","-i",str(source),"-vn","-ac","1","-ar","16000","-b:a","48k",str(out)], 300)
