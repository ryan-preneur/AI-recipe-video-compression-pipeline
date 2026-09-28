import json, os, shutil, sqlite3, threading, uuid
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()
ROOT = Path(os.getenv("DATA_DIR", "./data")).resolve()
ROOT.mkdir(parents=True, exist_ok=True)
DB = ROOT / "jobs.sqlite3"
_lock = threading.RLock()

def connect():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    return c

def init():
    with connect() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, url TEXT NOT NULL,
          duration INTEGER NOT NULL, output_language TEXT NOT NULL, state TEXT NOT NULL,
          stage TEXT NOT NULL, error TEXT, metadata TEXT, draft TEXT, output TEXT,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
init()

def create(url, duration, language):
    job_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    with _lock, connect() as c:
        c.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (job_id,url,duration,language,"queued","Waiting",None,None,None,None,now,now))
    (ROOT / job_id).mkdir()
    return job_id

def get(job_id):
    with connect() as c:
        r = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not r: return None
    v = dict(r)
    for k in ("metadata", "draft"):
        if v[k]: v[k] = json.loads(v[k])
    return v

def update(job_id, **fields):
    allowed = {"state","stage","error","metadata","draft","output"}
    assert fields.keys() <= allowed
    fields = {k: json.dumps(v, ensure_ascii=False) if k in {"metadata","draft"} and v is not None else v for k,v in fields.items()}
    fields["updated_at"] = datetime.now(timezone.utc).isoformat()
    with _lock, connect() as c:
        c.execute("UPDATE jobs SET "+", ".join(f"{k}=?" for k in fields)+" WHERE id=?", (*fields.values(),job_id))

def cleanup_expired(days=7):
    cutoff=datetime.now(timezone.utc).timestamp()-days*86400
    with _lock, connect() as c:
        rows=c.execute("SELECT id,created_at,state FROM jobs").fetchall()
        for row in rows:
            if row['state'] in {'processing','rendering','queued'}: continue
            try: created=datetime.fromisoformat(row['created_at']).timestamp()
            except ValueError: continue
            if created>=cutoff: continue
            folder=ROOT/row['id']
            if folder.is_dir(): shutil.rmtree(folder)
            c.execute("UPDATE jobs SET state='expired',stage='Temporary files expired',output=NULL WHERE id=?",(row['id'],))
