import { FormEvent, useRef, useState } from "react";

type Citation = {
  file_id: string;
  title: string;
  as_of: string;
  score: number;
  snippet: string;
};

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  cache_hit?: boolean;
};

const API = "http://127.0.0.1:8000";

const HINTS = [
  "What is the redemption notice period?",
  "What is the institutional expense ratio?",
  "What is the liquidity gate limit?",
];

export default function App() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [cacheBanner, setCacheBanner] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  async function send(text: string) {
    const q = text.trim();
    if (!q || busy) return;
    setBusy(true);
    setCacheBanner(null);
    setMessages((m) => [...m, { role: "user", content: q }]);
    setDraft("");

    const res = await fetch(`${API}/v1/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: q, session_id: sessionId }),
    });
    if (!res.ok || !res.body) {
      setMessages((m) => [
        ...m,
        { role: "assistant", content: `Request failed (${res.status}). Is the API running on port 8000?` },
      ]);
      setBusy(false);
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    let assistant = "";
    let citations: Citation[] = [];
    let hit = false;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop() ?? "";
      for (const part of parts) {
        const line = part.replace(/^data:\s*/, "");
        if (!line) continue;
        const ev = JSON.parse(line) as Record<string, unknown>;
        if (ev.type === "session" && typeof ev.session_id === "string") {
          setSessionId(ev.session_id);
        }
        if (ev.type === "cache_hit") {
          hit = Boolean(ev.value);
          setCacheBanner(hit ? "Repeated question — reused the previous answer (no new search)." : null);
        }
        if (ev.type === "token" && typeof ev.text === "string") {
          assistant = ev.text;
        }
        if (ev.type === "citations" && Array.isArray(ev.citations)) {
          citations = ev.citations as Citation[];
        }
      }
    }

    setMessages((m) => [
      ...m,
      { role: "assistant", content: assistant, citations, cache_hit: hit },
    ]);
    setBusy(false);
    queueMicrotask(() => listRef.current?.scrollTo(0, listRef.current.scrollHeight));
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void send(draft);
  }

  function newChat() {
    setSessionId(null);
    setMessages([]);
    setCacheBanner(null);
  }

  return (
    <>
      <header>
        <div>
          <h1>Horizon Trust knowledge assistant</h1>
          <p>
            MVP: ask about fund docs. New chat vs continue. Repeat a question to hit cache.
            {sessionId ? ` Session ${sessionId.slice(0, 8)}…` : " New conversation"}
          </p>
        </div>
        <button className="ghost" type="button" onClick={newChat}>
          New chat
        </button>
      </header>
      {cacheBanner ? <div className="banner">{cacheBanner}</div> : null}
      <div className="thread" ref={listRef}>
        {messages.length === 0 ? (
          <p style={{ color: "var(--muted)" }}>
            Indexed sample filings: redemption policy, fee schedule, liquidity risk. Try a hint below.
          </p>
        ) : null}
        {messages.map((m, i) => (
          <div className={`bubble ${m.role}`} key={i}>
            <div className="body">{m.content}</div>
            {m.citations && m.citations.length > 0 ? (
              <div className="cites">
                {m.citations.map((c) => (
                  <div className="cite" key={c.file_id + c.snippet.slice(0, 12)}>
                    <strong>{c.file_id}</strong> · {c.title} · {c.as_of} · score {c.score}
                    <div>{c.snippet}</div>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        ))}
      </div>
      <div className="hints">
        {HINTS.map((h) => (
          <button key={h} type="button" disabled={busy} onClick={() => void send(h)}>
            {h}
          </button>
        ))}
      </div>
      <form className="composer" onSubmit={onSubmit}>
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Ask about redemption, fees, or liquidity…"
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send(draft);
            }
          }}
        />
        <button className="primary" type="submit" disabled={busy}>
          {busy ? "…" : "Send"}
        </button>
      </form>
    </>
  );
}
