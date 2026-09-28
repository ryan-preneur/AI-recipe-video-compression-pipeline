"use client";
import { useEffect, useRef, useState } from "react";

type Segment = { start: number; end: number; text: string; uncertain: boolean };
type Cut = {
  id: string;
  source_start: number;
  source_end: number;
  purpose: string;
  source_evidence: string;
  narration_text: string;
  uncertain: boolean;
};
type Draft = {
  dish: string;
  source_language: string;
  output_language: string;
  transcript: Segment[];
  cuts: Cut[];
  warnings: string[];
};
type Job = {
  id: string;
  url: string;
  duration: number;
  output_language: string;
  state: string;
  stage: string;
  error: string | null;
  metadata?: {
    title: string;
    duration: number;
    thumbnail?: string;
    output_duration?: number;
    playback_speed?: number;
    usage?: {
      source_minutes: number;
      transcription_chunks: number;
      transcript_segments: number;
      voice_characters?: number;
    };
  };
};
const API = (
  process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000"
).replace(/\/$/, "");
const LANGS = [
  ["en", "English"],
  ["hi", "Hindi"],
  ["ta", "Tamil"],
  ["bn", "Bengali"],
  ["kn", "Kannada"],
];
function fmt(n: number) {
  const m = Math.floor(n / 60),
    s = Math.floor(n % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}
async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let r: Response;
  try {
    r = await fetch(API + path, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new Error(
      `Cannot connect to the backend at ${API}. Open ${API}/health in your browser, check that the backend terminal is running, then retry.`,
    );
  }
  if (!r.ok) {
    let message = `Request failed (${r.status})`;
    try {
      const j = await r.json();
      message =
        typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {}
    throw new Error(message);
  }
  return r.json();
}
export default function Home() {
  const [url, setUrl] = useState("");
  const [duration, setDuration] = useState(60);
  const [language, setLanguage] = useState("hi");
  const [sourceLanguage, setSourceLanguage] = useState("auto");
  const [speed, setSpeed] = useState(1.5);
  const [job, setJob] = useState<Job | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState("");
  const [saved, setSaved] = useState(true);
  const player = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    const id = localStorage.getItem("recipe-reel-job");
    if (id)
      req<Job>(`/jobs/${id}`)
        .then(setJob)
        .catch(() => localStorage.removeItem("recipe-reel-job"));
  }, []);
  useEffect(() => {
    if (!job) return;
    let alive = true;
    const tick = async () => {
      try {
        const j = await req<Job>(`/jobs/${job.id}`);
        if (!alive) return;
        setJob(j);
        if (j.state === "review" || j.state === "done") {
          if (!draft) {
            const d = await req<Draft>(`/jobs/${j.id}/draft`);
            if (alive) {
              setDraft(d);
              setSaved(true);
            }
          }
        }
      } catch (e) {
        if (alive) setMessage(String(e));
      }
    };
    tick();
    const timer = setInterval(tick, 2500);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [job?.id, job?.state, draft === null]);
  async function retry() {
    if (!job) return;
    setMessage("");
    setWorking(true);
    try {
      await req(`/jobs/${job.id}/retry`, { method: "POST" });
      setJob(await req<Job>(`/jobs/${job.id}`));
    } catch (e) {
      setMessage(String(e));
    } finally {
      setWorking(false);
    }
  }
  async function create(e: React.FormEvent) {
    e.preventDefault();
    setMessage("");
    setWorking(true);
    try {
      const x = await req<{ id: string }>("/jobs", {
        method: "POST",
        body: JSON.stringify({
          url,
          duration,
          output_language: language,
          source_language: sourceLanguage,
        }),
      });
      localStorage.setItem("recipe-reel-job", x.id);
      setDraft(null);
      setJob(await req<Job>(`/jobs/${x.id}`));
    } catch (e) {
      setMessage(String(e));
    } finally {
      setWorking(false);
    }
  }
  function edit(index: number, patch: Partial<Cut>) {
    setDraft((d) =>
      d
        ? {
            ...d,
            cuts: d.cuts.map((c, i) => (i === index ? { ...c, ...patch } : c)),
          }
        : d,
    );
    setSaved(false);
  }
  function editSegment(index: number, text: string) {
    setDraft((d) =>
      d
        ? {
            ...d,
            transcript: d.transcript.map((x, i) =>
              i === index ? { ...x, text } : x,
            ),
          }
        : d,
    );
    setSaved(false);
  }
  function remove(index: number) {
    setDraft((d) =>
      d ? { ...d, cuts: d.cuts.filter((_, i) => i !== index) } : d,
    );
    setSaved(false);
  }
  function move(index: number, offset: number) {
    setDraft((d) => {
      if (!d) return d;
      const cuts = [...d.cuts],
        to = index + offset;
      if (to < 0 || to >= cuts.length) return d;
      [cuts[index], cuts[to]] = [cuts[to], cuts[index]];
      return { ...d, cuts };
    });
    setSaved(false);
  }
  function preview(c: Cut) {
    if (player.current) {
      player.current.currentTime = c.source_start;
      player.current.play();
      const node = player.current;
      const stop = () => {
        if (node.currentTime >= c.source_end) {
          node.pause();
          node.removeEventListener("timeupdate", stop);
        }
      };
      node.addEventListener("timeupdate", stop);
    }
  }
  async function save() {
    if (!job || !draft) return;
    setMessage("");
    setWorking(true);
    try {
      const d = await req<Draft>(`/jobs/${job.id}/draft`, {
        method: "PUT",
        body: JSON.stringify({
          source_language: draft.source_language,
          transcript: draft.transcript,
          cuts: draft.cuts,
        }),
      });
      setDraft(d);
      setSaved(true);
      setMessage("Draft saved.");
    } catch (e) {
      setMessage(String(e));
    } finally {
      setWorking(false);
    }
  }
  async function replan() {
    if (!job || !draft) return;
    setMessage("");
    setWorking(true);
    try {
      await req(`/jobs/${job.id}/draft`, {
        method: "PUT",
        body: JSON.stringify({
          source_language: draft.source_language,
          transcript: draft.transcript,
          cuts: draft.cuts,
        }),
      });
      await req(`/jobs/${job.id}/replan`, { method: "POST" });
      setDraft(null);
      setJob(await req<Job>(`/jobs/${job.id}`));
    } catch (e) {
      setMessage(String(e));
    } finally {
      setWorking(false);
    }
  }
  async function generate() {
    if (!job || !draft) return;
    setMessage("");
    setWorking(true);
    try {
      if (!saved) {
        await req(`/jobs/${job.id}/draft`, {
          method: "PUT",
          body: JSON.stringify({
            source_language: draft.source_language,
            transcript: draft.transcript,
            cuts: draft.cuts,
          }),
        });
        setSaved(true);
      }
      await req(`/jobs/${job.id}/render`, {
        method: "POST",
        body: JSON.stringify({ speed }),
      });
      setJob(await req<Job>(`/jobs/${job.id}`));
    } catch (e) {
      setMessage(String(e));
    } finally {
      setWorking(false);
    }
  }
  const speedControl = (
    <div className="speedControl">
      <label htmlFor="reel-speed">VIDEO PLAYBACK SPEED</label>
      <select
        id="reel-speed"
        value={speed}
        onChange={(e) => setSpeed(Number(e.target.value))}
      >
        {[1, 1.25, 1.5, 1.75, 2, 2.5, 3, 4].map((x) => (
          <option key={x} value={x}>
            {x}×
            {x === 1
              ? " (normal)"
              : x > 2
                ? " (very fast)"
                : x >= 1.75
                  ? " (fast)"
                  : " (slightly faster)"}
          </option>
        ))}
      </select>
      <p className="hint">
        Higher speed shortens the visuals to help fit your {job?.duration}s
        target. Narration stays at normal speed. Export fills a vertical 9:16
        frame, so some side edges may be cropped.
      </p>
    </div>
  );
  const total =
    draft?.cuts.reduce((v, c) => v + c.source_end - c.source_start, 0) || 0;
  const projectedVisualSeconds = total / speed;
  return (
    <main className="shell">
      <header>
        <div className="brand">
          <span className="logo">◌</span> RECIPE REEL{" "}
          <span className="studio">STUDIO</span>
        </div>
        <span className="badge">LOCAL V1</span>
      </header>
      <section className="hero">
        <p className="eyebrow">FROM A FULL RECIPE TO THE ESSENTIAL STEPS</p>
        <h1>
          Cook the whole story.
          <br />
          <em>Watch only what matters.</em>
        </h1>
        <p className="intro">
          Paste a recipe video, choose a length and listening language, then
          review the exact moments before your short video is made.
        </p>
      </section>
      {!job && (
        <section className="card setup">
          <form onSubmit={create}>
            <label htmlFor="url">YOUTUBE RECIPE LINK</label>
            <input
              id="url"
              type="url"
              placeholder="https://www.youtube.com/watch?v=..."
              required
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
            <div className="formgrid">
              <div>
                <label>REEL LENGTH</label>
                <div className="choices">
                  {[30, 60, 90, 120].map((n) => (
                    <button
                      type="button"
                      key={n}
                      className={duration === n ? "selected" : ""}
                      onClick={() => setDuration(n)}
                    >
                      {n < 60 ? `${n}s` : `${n / 60} min`}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label htmlFor="source-lang-select">SOURCE SPEECH</label>
                <select
                  id="source-lang-select"
                  value={sourceLanguage}
                  onChange={(e) => setSourceLanguage(e.target.value)}
                >
                  <option value="auto">Auto detect</option>
                  {LANGS.map(([id, name]) => (
                    <option key={id} value={id}>
                      {name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label htmlFor="lang">LISTEN IN</label>
                <select
                  id="lang"
                  value={language}
                  onChange={(e) => setLanguage(e.target.value)}
                >
                  {LANGS.map(([id, name]) => (
                    <option key={id} value={id}>
                      {name}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <button className="primary" disabled={working}>
              {working ? "Starting…" : "Analyze recipe"} <span>→</span>
            </button>
          </form>
          <p className="note">
            Use videos you have permission to process. You can edit every cut
            before export.
          </p>
        </section>
      )}
      {job && (
        <>
          <div className="jobbar">
            <div>
              <span className="eyebrow">CURRENT RECIPE</span>
              <h2>{job.metadata?.title || "Preparing your video…"}</h2>
              <p>
                {job.duration}s target ·{" "}
                {LANGS.find((x) => x[0] === job.output_language)?.[1]} narration
              </p>
            </div>
            <button
              className="subtle"
              onClick={() => {
                localStorage.removeItem("recipe-reel-job");
                setJob(null);
                setDraft(null);
                setMessage("");
              }}
            >
              New recipe
            </button>
          </div>
          <div className={`status ${job.state}`}>
            <span className="pulse" />
            {job.stage}
            {job.state === "processing" || job.state === "rendering" ? (
              <span className="small"> This may take a few minutes.</span>
            ) : null}
          </div>
          {job.error && (
            <div className="error">
              {job.error}
              {job.state === "failed" && (
                <button
                  className="subtle retry"
                  disabled={working}
                  onClick={retry}
                >
                  Retry analysis
                </button>
              )}
            </div>
          )}
        </>
      )}
      {job && draft && (
        <>
          <section className="review">
            <div className="videoPanel">
              <div className="sectionhead">
                <div>
                  <p className="eyebrow">SOURCE VIDEO</p>
                  <h2>Check each moment</h2>
                </div>
              </div>
              <video
                ref={player}
                controls
                preload="metadata"
                src={`${API}/jobs/${job.id}/source`}
              />
              <p className="hint">
                Play a proposed clip to confirm the action and adjust its times
                below.
              </p>
              <details>
                <summary>
                  Source transcript ({draft.transcript.length} segments)
                </summary>
                <div className="transcript">
                  <label htmlFor="source-lang">SPOKEN LANGUAGE</label>
                  <select
                    id="source-lang"
                    value={draft.source_language}
                    onChange={(e) => {
                      setDraft({ ...draft, source_language: e.target.value });
                      setSaved(false);
                    }}
                  >
                    <option value="unknown">Unknown</option>
                    {LANGS.map(([id, name]) => (
                      <option key={id} value={id}>
                        {name}
                      </option>
                    ))}
                  </select>
                  {draft.transcript.map((s, i) => (
                    <div className="segment" key={i}>
                      <b>
                        {fmt(s.start)}–{fmt(s.end)}
                      </b>
                      <textarea
                        aria-label={`Transcript ${i + 1}`}
                        value={s.text}
                        onChange={(e) => editSegment(i, e.target.value)}
                        rows={2}
                      />
                      {s.uncertain && (
                        <span className="flag"> check timing</span>
                      )}
                    </div>
                  ))}
                  <button
                    className="subtle"
                    disabled={working}
                    onClick={replan}
                  >
                    Replan from corrected transcript
                  </button>
                </div>
              </details>
            </div>
            <div className="editPanel">
              <div className="sectionhead">
                <div>
                  <p className="eyebrow">THE SHORT VERSION</p>
                  <h2>{draft.dish}</h2>
                </div>
                <strong>
                  {Math.round(total)}s <small>/ {job.duration}s</small>
                </strong>
              </div>
              {draft.warnings.map((w, i) => (
                <p className="warning" key={i}>
                  ⚑ {w}
                </p>
              ))}
              <div className="cuts">
                {draft.cuts.map((c, i) => (
                  <article className="cut" key={c.id}>
                    <div className="cuttop">
                      <span className="index">
                        {String(i + 1).padStart(2, "0")}
                      </span>
                      <input
                        aria-label="Step purpose"
                        className="purpose"
                        value={c.purpose}
                        onChange={(e) => edit(i, { purpose: e.target.value })}
                      />
                      <button
                        title="Preview source clip"
                        onClick={() => preview(c)}
                      >
                        ▶ Preview
                      </button>
                    </div>
                    <div className="times">
                      <label>
                        START{" "}
                        <input
                          type="number"
                          min="0"
                          step="0.1"
                          value={c.source_start}
                          onChange={(e) =>
                            edit(i, { source_start: Number(e.target.value) })
                          }
                        />
                      </label>
                      <label>
                        END{" "}
                        <input
                          type="number"
                          min="0"
                          step="0.1"
                          value={c.source_end}
                          onChange={(e) =>
                            edit(i, { source_end: Number(e.target.value) })
                          }
                        />
                      </label>
                      <span>
                        {fmt(Math.max(0, c.source_end - c.source_start))}
                      </span>
                    </div>
                    <label className="narration">
                      NARRATION IN{" "}
                      {LANGS.find(
                        (x) => x[0] === job.output_language,
                      )?.[1]?.toUpperCase()}
                      <textarea
                        value={c.narration_text}
                        onChange={(e) =>
                          edit(i, { narration_text: e.target.value })
                        }
                        rows={2}
                      />
                    </label>
                    <p className="evidence">Source: {c.source_evidence}</p>
                    {c.uncertain && (
                      <span className="flag">Review this cut</span>
                    )}
                    <div className="cutactions">
                      <button disabled={i === 0} onClick={() => move(i, -1)}>
                        ↑ Earlier
                      </button>
                      <button
                        disabled={i === draft.cuts.length - 1}
                        onClick={() => move(i, 1)}
                      >
                        ↓ Later
                      </button>
                      <button onClick={() => remove(i)}>Remove</button>
                    </div>
                  </article>
                ))}
              </div>
              {projectedVisualSeconds > job.duration + 5 && (
                <p className="warning">
                  At {speed}×, these visuals are about {Math.ceil(projectedVisualSeconds)}s. Increase speed or shorten the clips to fit the {job.duration}s target.
                </p>
              )}
              {speedControl}
              <div className="actions">
                <button
                  className="subtle"
                  disabled={working || saved}
                  onClick={save}
                >
                  {saved ? "Saved" : "Save edits"}
                </button>
                <button
                  className="primary"
                  disabled={
                    working ||
                    !draft.cuts.length ||
                    job.state === "rendering" ||
                    projectedVisualSeconds > job.duration + 5
                  }
                  onClick={generate}
                >
                  {job.state === "rendering" ? "Rendering…" : "Generate reel"}{" "}
                  <span>→</span>
                </button>
              </div>
            </div>
          </section>
        </>
      )}
      {job?.state === "done" && (
        <section className="card result">
          <div>
            <p className="eyebrow">READY TO COOK</p>
            <h2>Your recipe reel</h2>
            <p>
              {Math.round(job.metadata?.output_duration || 0)} seconds ·{" "}
              {job.metadata?.playback_speed || 1}× visuals · vertical 9:16 ·{" "}
              {LANGS.find((x) => x[0] === job.output_language)?.[1]} narration
            </p>
          </div>
          <video controls src={`${API}/jobs/${job.id}/output`}>
            <track
              kind="captions"
              src={`${API}/jobs/${job.id}/captions`}
              srcLang={job.output_language}
              label="Recipe captions"
              default
            />
          </video>
          <a className="primary download" href={`${API}/jobs/${job.id}/output`}>
            Download MP4 ↓
          </a>
          {job.metadata?.usage && (
            <details>
              <summary>Processing usage</summary>
              <p className="hint">
                Source: {job.metadata.usage.source_minutes} minutes · Speech
                transcription chunks: {job.metadata.usage.transcription_chunks}{" "}
                · Narration: {job.metadata.usage.voice_characters || 0}{" "}
                characters. These are usage counts, not a bill.
              </p>
            </details>
          )}
        </section>
      )}
      {message && (
        <p role="status" className="message">
          {message}
        </p>
      )}
      <footer>
        Recipe Reel Studio · A short guide should still make sense as a recipe.
      </footer>
    </main>
  );
}
