// H4 (S-31) — phone companion. Touch, not D-pad: this page never runs on the TV.
// `/companion` asks for the 4-digit code the TV shows on /tv/pair; `/companion/:code`
// skips straight to the query box. The socket is opened with the code itself (D-16).
//
// M13: the TV pushes `now` {game_id, title, t} once a second while a game is on screen.
// "Clip that" posts a tap at that media time (POST /games/{id}/triggers — the API cuts
// the play that just ended, D-50) and tells the TV, which shows a toast. Search runs
// POST /games/{id}/search here and "Play on TV" sends the hit's start as a `seek`.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, sessionWsUrl } from "../api/client";
import { navigate } from "../router";
import { fmtClock, type SearchResult } from "../../../../packages/tv-core/src/discovery";

type Status = "idle" | "connecting" | "open" | "closed";
type Now = { game_id: string; title?: string; t: number };

/** Chrome/Edge only; the mic button is hidden everywhere else. */
interface SpeechRecognitionLike {
  lang: string;
  interimResults: boolean;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
}
type SpeechCtor = new () => SpeechRecognitionLike;

function speechCtor(): SpeechCtor | null {
  const w = window as unknown as { webkitSpeechRecognition?: SpeechCtor; SpeechRecognition?: SpeechCtor };
  return w.webkitSpeechRecognition ?? w.SpeechRecognition ?? null;
}

export function Companion({ code }: { code?: string }) {
  const [entry, setEntry] = useState("");
  const [text, setText] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [sent, setSent] = useState<string | null>(null);
  const [listening, setListening] = useState(false);
  const [now, setNow] = useState<Now | null>(null);
  const [clipNote, setClipNote] = useState("");
  const [find, setFind] = useState("");
  const [found, setFound] = useState<SearchResult | null>(null);
  const [findError, setFindError] = useState("");
  const ws = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!code) return;
    setStatus("connecting");
    const sock = new WebSocket(sessionWsUrl(code));
    ws.current = sock;
    sock.onopen = () => setStatus("open");
    sock.onclose = () => setStatus("closed");
    sock.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data as string) as { type?: string } & Partial<Now>;
        if (msg.type === "now" && msg.game_id && typeof msg.t === "number") {
          setNow({ game_id: msg.game_id, title: msg.title, t: msg.t });
        }
      } catch {
        /* not ours */
      }
    };
    return () => {
      ws.current = null;
      // A socket torn down by a re-run (StrictMode, a new code) must not report its own
      // close as the session's: its `close` event can land after the new one is open.
      sock.onopen = sock.onclose = sock.onmessage = null;
      sock.close();
    };
  }, [code]);

  const push = useCallback((msg: object) => {
    if (ws.current?.readyState !== WebSocket.OPEN) return false;
    ws.current.send(JSON.stringify(msg));
    return true;
  }, []);

  const send = useCallback(
    (query: string) => {
      const q = query.trim();
      if (!q || !push({ type: "query", text: q })) return;
      setSent(q);
      setText("");
    },
    [push],
  );

  const clipThat = useCallback(() => {
    if (!now) return;
    setClipNote("Clipping…");
    api.tap(now.game_id, now.t).then(
      (r) => {
        const label = r.clip
          ? `Clip saved · ${fmtClock(r.clip.t_start)}–${fmtClock(r.clip.t_end)}`
          : "Tap saved · no play had just ended";
        setClipNote(label);
        push({ type: "clip", label });
      },
      (e: Error) => setClipNote(`Not clipped: ${e.message}`),
    );
  }, [now, push]);

  const search = useCallback(() => {
    const q = find.trim();
    if (!now || !q) return;
    setFindError("");
    api.search(now.game_id, q).then(setFound, (e: Error) => {
      setFound(null);
      setFindError(e.message);
    });
  }, [now, find]);

  const Speech = speechCtor();
  const listen = useCallback(() => {
    const Ctor = speechCtor();
    if (!Ctor) return;
    const rec = new Ctor();
    rec.lang = "en-US";
    rec.interimResults = false;
    rec.onresult = (e) => setText(e.results[0][0].transcript);
    rec.onend = () => setListening(false);
    setListening(true);
    rec.start();
  }, []);

  if (!code) {
    return (
      <div className="screen phone companion">
        <h1>Replay companion</h1>
        <p>Enter the 4-digit code shown on the TV.</p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (/^\d{4}$/.test(entry)) navigate(`/companion/${entry}`);
          }}
        >
          <input
            data-testid="companion-code-input"
            inputMode="numeric"
            pattern="\d{4}"
            maxLength={4}
            value={entry}
            onChange={(ev) => setEntry(ev.target.value.replace(/\D/g, "").slice(0, 4))}
            placeholder="0000"
            autoFocus
          />
          <button type="submit" data-testid="companion-connect" disabled={!/^\d{4}$/.test(entry)}>
            Connect
          </button>
        </form>
      </div>
    );
  }

  return (
    <div className="screen phone companion">
      <h1>Replay companion</h1>
      <p className="status-line">
        Code {code} ·{" "}
        <span className="conn" data-testid="companion-status" data-state={status}>
          {status === "open" ? "connected" : status === "closed" ? "not connected" : "connecting…"}
        </span>
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(text);
        }}
      >
        <input
          data-testid="companion-query"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Marcus — all shots"
          autoFocus
        />
        <div className="actions">
          <button
            type="submit"
            data-testid="companion-send"
            disabled={status !== "open" || !text.trim()}
          >
            Send
          </button>
          {Speech ? (
            <button
              type="button"
              className="secondary"
              data-testid="companion-mic"
              data-listening={listening ? "true" : "false"}
              onClick={listen}
            >
              {listening ? "Listening…" : "Speak"}
            </button>
          ) : null}
        </div>
      </form>
      {sent ? <p data-testid="companion-sent">Sent: {sent}</p> : null}

      <h2>Replay, clip that</h2>
      <p className="dim" data-testid="companion-now" data-game-id={now?.game_id ?? ""}>
        {now
          ? `On the TV: ${now.title ?? now.game_id} · ${fmtClock(now.t)}`
          : "Open a game on the TV to clip it from here."}
      </p>
      <button
        type="button"
        className="clip-that"
        data-testid="companion-clip"
        disabled={status !== "open" || !now}
        onClick={clipThat}
      >
        Clip that
      </button>
      {clipNote ? <p data-testid="companion-clip-result">{clipNote}</p> : null}

      <h2>Search this game</h2>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          search();
        }}
      >
        <input
          data-testid="companion-search"
          value={find}
          onChange={(e) => setFind(e.target.value)}
          placeholder="Marcus — all shots"
        />
        <button type="submit" data-testid="companion-search-go" disabled={!now || !find.trim()}>
          Search
        </button>
      </form>
      {findError ? <p className="error">Search failed: {findError}</p> : null}
      {found ? (
        <>
          <p className="dim" data-testid="companion-search-interpretation" data-fallback={found.fallback ? "true" : "false"}>
            {found.interpretation}
            {found.fallback ? " · keyword match" : ""}
          </p>
          <ul className="phone-hits">
            {found.results.map((h, i) => (
              <li key={`${h.play_id}-${i}`} data-testid="companion-hit" data-t-start={h.t_start}>
                <span>
                  {fmtClock(h.t_start)} · {h.text}
                </span>
                <button
                  type="button"
                  className="secondary"
                  data-testid="companion-play"
                  disabled={status !== "open"}
                  onClick={() => push({ type: "seek", t: h.t_start })}
                >
                  Play on TV
                </button>
              </li>
            ))}
          </ul>
        </>
      ) : null}

      {status === "closed" ? (
        <p className="error" data-testid="companion-error">
          That code is not paired. Check the code on the TV.{" "}
          <button type="button" onClick={() => navigate("/companion")}>
            Try again
          </button>
        </p>
      ) : null}
    </div>
  );
}
