import { FormEvent, useEffect, useRef, useState } from "react";

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

const API = "";

const HINTS = [
  "What is the redemption notice period?",
  "What is the institutional expense ratio?",
  "What is the liquidity gate limit?",
];

export default function App() {
  const [userId, setUserId] = useState("analyst-1");
  const [token, setToken] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [cacheBanner, setCacheBanner] = useState<string | null>(null);
  const [redisOn, setRedisOn] = useState<boolean | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  async function signIn(id: string) {
    const res = await fetch(`${API}/v1/auth/token`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: id.trim() || "analyst-1" }),
    });
    if (!res.ok) {
      throw new Error(`Sign-in failed (${res.status})`);
    }
    const data = (await res.json()) as { access_token: string; user_id: string };
    setToken(data.access_token);
    setUserId(data.user_id);
    localStorage.setItem("agenticrag_user", data.user_id);
    localStorage.setItem("agenticrag_token", data.access_token);
  }

  useEffect(() => {
    const savedUser = localStorage.getItem("agenticrag_user") || "analyst-1";
    setUserId(savedUser);
    void signIn(savedUser).catch(() => setToken(null));
  }, []);

  async function send(text: string) {
    const q = text.trim();
    if (!q || busy) return;
    if (!token) {
      setMessages((m) => [
        ...m,
        { role: "assistant", content: "Not signed in. Enter a user id and click Sign in. Is the API running?" },
      ]);
      return;
    }
    setBusy(true);
    setCacheBanner(null);
    setMessages((m) => [...m, { role: "user", content: q }]);
    setDraft("");

    let res: Response;
    try {
      res = await fetch(`${API}/v1/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ message: q, session_id: sessionId }),
      });
    } catch {
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content:
            "Could not reach the API. Start Redis (docker compose up -d redis), then uvicorn on port 8000.",
        },
      ]);
      setBusy(false);
      return;
    }
    if (res.status === 401) {
      setMessages((m) => [...m, { role: "assistant", content: "Token expired or invalid. Click Sign in." }]);
      setBusy(false);
      return;
    }
    if (!res.ok || !res.body) {
      setMessages((m) => [
        ...m,
        { role: "assistant", content: `Request failed (${res.status}). Is uvicorn running on port 8000?` },
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
          if (typeof ev.redis === "boolean") setRedisOn(ev.redis);
        }
        if (ev.type === "cache_hit") {
          hit = Boolean(ev.value);
          setCacheBanner(
            hit
              ? "Redis hit — same user, chat, question, and index version. No new search."
              : null
          );
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
      {
        role: "assistant",
        content: assistant || "No answer came back. Confirm uvicorn is running on port 8000.",
        citations,
        cache_hit: hit,
      },
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
            JWT + Redis cache (TTL). Repeat a question in this chat for a hit.
            {sessionId ? ` Session ${sessionId.slice(0, 8)}…` : " New conversation"}
            {redisOn === null ? "" : redisOn ? " · Redis on" : " · Redis off (in-process answers only, no shared cache)"}
          </p>
        </div>
        <div className="auth">
          <input
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
            aria-label="User id"
            placeholder="user id"
          />
          <button
            className="ghost"
            type="button"
            onClick={() => {
              newChat();
              void signIn(userId).catch(() => setToken(null));
            }}
          >
            Sign in
          </button>
          <button className="ghost" type="button" onClick={newChat}>
            New chat
          </button>
        </div>
      </header>
      {cacheBanner ? <div className="banner">{cacheBanner}</div> : null}
      <div className="thread" ref={listRef}>
        {messages.length === 0 ? (
          <p style={{ color: "var(--muted)" }}>
            Sign in as analyst-1, ask a question, ask it again (Redis hit). Sign in as analyst-2 and
            the same question is a miss — different user id in the cache key.
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
