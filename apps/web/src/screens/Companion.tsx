// H4 (S-31) — phone companion. Touch, not D-pad: this page never runs on the TV.
// `/companion` asks for the 4-digit code the TV shows on /tv/pair; `/companion/:code`
// skips straight to the query box. The socket is opened with the code itself (D-16).
import { useCallback, useEffect, useRef, useState } from "react";
import { sessionWsUrl } from "../api/client";
import { navigate } from "../router";

type Status = "idle" | "connecting" | "open" | "closed";

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
  const ws = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!code) return;
    setStatus("connecting");
    const sock = new WebSocket(sessionWsUrl(code));
    ws.current = sock;
    sock.onopen = () => setStatus("open");
    sock.onclose = () => setStatus("closed");
    return () => {
      ws.current = null;
      sock.close();
    };
  }, [code]);

  const send = useCallback(
    (query: string) => {
      const q = query.trim();
      if (!q || ws.current?.readyState !== WebSocket.OPEN) return;
      ws.current.send(JSON.stringify({ type: "query", text: q }));
      setSent(q);
      setText("");
    },
    [],
  );

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
