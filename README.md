# Recipe Reel Studio

A local V1 for turning a public YouTube recipe into a reviewed 30, 60, 90, or 120 second instructional MP4. Exports fill a vertical 9:16 frame and may crop the source video sides. Select 1× to 4× visual speed before generating; the narration remains normal speed. Source speech can be multilingual; output narration can be English, Hindi, Tamil, Bengali, or Kannada. The user must review the draft cuts and script before generation.

## Windows: install once, then update this same folder

This folder is intended to be your permanent Recipe Reel Studio folder. Do **not** download and extract a new ZIP for later releases. Once the one-time Git setup below is complete, double-click `Update-App.bat` whenever you want the latest version in this very folder. It updates program files only and leaves these local files untouched:

- `backend/.env` — your Gemini API key and local settings
- `frontend/.env.local` — your frontend local setting
- `backend/data` — jobs, downloaded source files, and completed exports

`Start-App.bat` opens a backend PowerShell window and a frontend PowerShell window. Keep both open while using the app, then open the local address printed by the frontend window (normally `http://localhost:3000`).

### One-time private GitHub setup

First install these free prerequisites if needed: [Git for Windows](https://git-scm.com/download/win), Python 3.11 or newer, Node.js 20 or newer, and FFmpeg (including `ffprobe`) on your PATH. Close and reopen PowerShell after installing them.

1. Create a **new private** repository on GitHub. Leave GitHub's “Add a README”, `.gitignore`, and license boxes unchecked, because this folder already contains them. Copy the repository HTTPS address (it ends in `.git`).
2. Open PowerShell in this folder. In File Explorer, click the address bar, type `powershell`, and press Enter.
3. Run these commands, replacing the example address with the private repository address you copied. They publish only when you run the final `git push` command.

```powershell
git init
git add .
git commit -m "Initial Recipe Reel Studio"
git branch -M main
git remote add origin https://github.com/YOUR-ACCOUNT/recipe-reel-studio.git
git push -u origin main
```

Git may open a browser so you can sign in to GitHub. Never put an API key in a Git command, GitHub repository, or frontend file. The supplied `.gitignore` excludes the private settings and job data above; verify with `git status` before the first commit that they do not appear.

### Everyday update and start

1. Close the two app PowerShell windows if the app is running.
2. Double-click `Update-App.bat`. It downloads the latest committed code into this same folder, installs backend or frontend dependencies only when their dependency files changed, and stops safely if you have uncommitted code changes.
3. Double-click `Start-App.bat`.

You can also run the scripts from PowerShell:

```powershell
.\Update-App.ps1
.\Start-App.ps1
```

If the update script says no remote is configured, complete the one-time GitHub setup above. If it says you have uncommitted changes, save them with `git add .`, `git commit -m "Describe my change"`, then run the update again. It never logs the contents of `.env` files.

## Requirements

- Python 3.11+, Node 20+, FFmpeg/ffprobe on PATH.
- Gemini API key for planning, fallback transcription, and narration.
- Access to the configured Gemini speech model for narrated export; model availability and quota depend on your account.
- A public video you may process. Some YouTube URLs cannot be retrieved; the app reports that as an error.

## Run locally

In terminal 1:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env     # On Windows, copy the file instead
# Edit .env with your Gemini API key.
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

In terminal 2:

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

Open http://localhost:3000. Do not put keys in the frontend environment file. API docs: http://localhost:8000/docs.

The app fetches captions when usable, otherwise sends 20-second audio chunks for transcription. Fallback chunks provide coarse timestamps, so inspect cuts carefully before rendering. The output video has a selectable subtitle track and an accompanying VTT in the local job folder. Source speech is muted in the narrated output; useful cooking sounds are not preserved yet. Landscape footage is letterboxed into a vertical 720 × 1280 frame. A voice line up to nine seconds longer than its source shot freezes the last frame; longer lines require editing.

## Local checks

```bash
cd backend
python -m unittest discover -s tests -v
python -m compileall -q app
```

The project does not contain API credentials, downloaded videos, or paid-service fixtures. A true end-to-end test needs your credentials, a source video you may process, and connectivity to the providers. Check transcript quality and regional pronunciation on real examples before trusting an export. Do not publish raw source videos or derivatives without the required rights.

## Project layout

- `frontend/app/page.tsx`: input, job progress, source review, cut editor, and download UI.
- `backend/app/media.py`: URL validation, retrieval, and media probing.
- `backend/app/intelligence.py`: caption/ASR transcript and recipe clip planner.
- `backend/app/render.py`: multilingual voice, cuts, MP4, and subtitles.
- `backend/app/main.py`: API routes and local jobs.

This is a local single-user V1. A hosted version needs authentication, isolated background workers, object storage, per-user quotas, and source-file cleanup.

Temporary job media is removed on server startup after `RETENTION_DAYS` (default seven days), except jobs currently processing. Completed files must be downloaded before expiry. The result page shows source minutes, speech transcription chunks, and narration characters as usage indicators, not a monetary bill.

## Windows PowerShell setup and connection check

Run these in the extracted `recipe-reel` directory. In the backend terminal:

```powershell
cd backend
Copy-Item .env.example .env
notepad .env
```

Put your Gemini API key after `GEMINI_API_KEY=` in the **backend** `.env` file, save, and restart the backend. Keep this file private. The same key is used at Analyze and Generate. Gemini speech generation may have different availability or billing than text generation.

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/health` and check that it returns `"ok": true`. Leave this terminal running. In a second terminal:

```powershell
cd frontend
Copy-Item .env.example .env.local
notepad .env.local
```

Ensure it says `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000`, then run `npm install` and `npm run dev`. Restart `npm run dev` after changing `.env.local`. Open the exact local address printed by Next.js (it may use port 3001 if 3000 is busy).

If Analyze shows **Cannot connect to the backend**, check `/health`, the backend terminal, and the frontend API URL. A React hydration warning showing `jf-ext-*` attributes is caused by a browser extension changing the page; try an Incognito window with extensions disabled. It is separate from API connectivity.

## YouTube subtitle rate limits

The downloader obtains source video first and requests at most one relevant caption track. If YouTube returns HTTP 429 for captions, analysis continues by transcribing the audio with Gemini. This costs more API calls and gives coarse 20-second transcript blocks, so review cut timing carefully. If the video download itself is rate limited, the app reports the failure; retry later with a different available video rather than repeatedly submitting the same URL. Impersonation warnings from yt-dlp are separate from subtitle rate limits.

After updating from an earlier V1 build, preserve `backend/.env`, `frontend/.env.local`, and `backend/data`. If a prior analysis failed during subtitle download, click **Retry analysis** on that job. The updated backend reuses its downloaded source when present and falls back to speech transcription. Restart both terminals after replacing code.

## Switching from an earlier build

In `backend/.env`, replace the old OpenAI and Google Cloud settings with `GEMINI_API_KEY=...`. Keep the existing `backend/data` and `frontend/.env.local` directories when updating. Install backend requirements again, then restart both terminals. The key shared in chat should be revoked and replaced with a new one in Google AI Studio. Never paste a key into frontend files or commit it to source control.

## Gemini 503 high demand

The backend retries temporary Gemini server errors three times with short increasing delays, then switches to `GEMINI_FALLBACK_MODEL` for analysis or `GEMINI_TTS_FALLBACK_MODEL` for narration. This does not bypass account limits or guarantee availability. Set `GEMINI_MODEL=gemini-3.8-flash` and `GEMINI_FALLBACK_MODEL=gemini-3.5-flash-lite`. The backend automatically maps obsolete 2.5 or `gemini-flash-latest` values from an older `.env` to these supported models. Restart the backend and click **Retry analysis** on a failed analysis; a failed Generate can be tried again once service recovers. If your account cannot access a fallback, remove its value from `.env`. Check model availability and any applicable charges in Google AI Studio.

## Gemini 429 quota exceeded

If narration reports HTTP 429 or “quota exceeded” for `gemini-3.8-flash-tts`, the provider has declined the request because of its quota or rate limit. Recipe Reel Studio does not retry the request and does not send it to a fallback model, which prevents accidental repeat requests. Wait for the quota to reset and check your available model/quota in Google AI Studio before trying **Generate reel** once again. The app cannot increase quota or turn on paid billing for you.
