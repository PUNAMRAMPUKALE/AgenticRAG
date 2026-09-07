import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { GoogleLogin, GoogleOAuthProvider } from "@react-oauth/google";
import { apiFetch, fetchMe, loadAuthConfig, signInWithGoogleIdToken, signOut as apiSignOut, type Me } from "./auth";

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

type ConvoSummary = {
  session_id: string;
  title: string;
  message_count: number;
};

const HINTS = [
  "What is the redemption notice period?",
  "What is the institutional expense ratio?",
  "What is the liquidity gate limit?",
];

function roleLabel(role: string): string {
  if (role === "manager") return "manager (expert)";
  if (role === "senior_analyst") return "senior analyst";
  if (role === "analyst") return "analyst";
  return role;
}

export default function App() {
  const [ready, setReady] = useState(false);
  const [clientId, setClientId] = useState("");
  const [me, setMe] = useState<Me | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversations, setConversations] = useState<ConvoSummary[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [cacheBanner, setCacheBanner] = useState<string | null>(null);
  const [redisOn, setRedisOn] = useState<boolean | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const isManager = Boolean(me?.roles.includes("manager"));

  const loadConversations = useCallback(async () => {
    const res = await apiFetch("/v1/conversations");
    if (!res.ok) {
      setConversations([]);
      return;
    }
    const data = (await res.json()) as { conversations: ConvoSummary[] };
    setConversations(data.conversations);
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const cfg = await loadAuthConfig();
        if (cancelled) return;
        setClientId(cfg.client_id);
        const profile = await fetchMe();
        if (cancelled) return;
        setMe(profile);
        if (profile) await loadConversations();
      } catch (err) {
        if (!cancelled) {
          setAuthError(err instanceof Error ? err.message : "Could not reach the API");
          setMe(null);
        }
      } finally {
        if (!cancelled) setReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loadConversations]);

  async function onGoogle(idToken: string) {
    setAuthError(null);
    try {
      const profile = await signInWithGoogleIdToken(idToken);
      setMe(profile);
      await loadConversations();
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : "Google sign-in failed");
    }
  }

  async function signOut() {
    await apiSignOut();
    setMe(null);
    setConversations([]);
    setSessionId(null);
    setMessages([]);
  }

  async function openConversation(id: string) {
    const res = await apiFetch(`/v1/conversations/${id}`);
    if (!res.ok) return;
    const data = (await res.json()) as { session_id: string; messages: ChatMessage[] };
    setSessionId(data.session_id);
    setMessages(data.messages);
    setCacheBanner(null);
  }

  async function reindex() {
    const res = await apiFetch("/v1/reindex", { method: "POST" });
    if (res.status === 403) {
      setCacheBanner("Reindex requires the manager (expert) role.");
      return;
    }
    if (!res.ok) {
      setCacheBanner(`Reindex failed (${res.status}).`);
      return;
    }
    const data = (await res.json()) as { index_version: string; flushed_keys: number };
    setCacheBanner(`Reindexed. Version ${data.index_version}. Flushed ${data.flushed_keys} cache keys.`);
  }

  async function send(text: string) {
    const q = text.trim();
    if (!q || busy) return;
    setBusy(true);
    setCacheBanner(null);
    setMessages((m) => [...m, { role: "user", content: q }]);
    setDraft("");

    let res: Response;
    try {
      res = await apiFetch("/v1/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: q, session_id: sessionId }),
      });
    } catch {
      setMessages((m) => [
        ...m,
        { role: "assistant", content: "Could not reach the API. Is uvicorn running on port 8000?" },
      ]);
      setBusy(false);
      return;
    }
    if (res.status === 401) {
      setMe(null);
      setMessages((m) => [...m, { role: "assistant", content: "Session expired. Sign in with Google again." }]);
      setBusy(false);
      return;
    }
    if (res.status === 403) {
      setMessages((m) => [
        ...m,
        { role: "assistant", content: "You do not have permission to chat." },
      ]);
      setBusy(false);
      return;
    }
    if (!res.ok || !res.body) {
      setMessages((m) => [...m, { role: "assistant", content: `Request failed (${res.status}).` }]);
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
            hit ? "Redis hit — same user, chat, question, and index version. No new search." : null
          );
        }
        if (ev.type === "token" && typeof ev.text === "string") assistant = ev.text;
        if (ev.type === "citations" && Array.isArray(ev.citations)) {
          citations = ev.citations as Citation[];
        }
      }
    }

    setMessages((m) => [
      ...m,
      {
        role: "assistant",
        content: assistant || "No answer came back.",
        citations,
        cache_hit: hit,
      },
    ]);
    setBusy(false);
    void loadConversations();
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

  if (!ready) {
    return (
      <div className="gate">
        <p>Checking session…</p>
      </div>
    );
  }

  if (!me) {
    return (
      <div className="gate">
        <h1>Horizon Trust knowledge assistant</h1>
        <p>Sign in with Google. The API verifies the Google ID token and stores an httpOnly session.</p>
        {authError ? <p className="gate-error">{authError}</p> : null}
        {clientId ? (
          <GoogleOAuthProvider clientId={clientId}>
            <GoogleLogin
              onSuccess={(cred) => {
                if (cred.credential) void onGoogle(cred.credential);
              }}
              onError={() => setAuthError("Google sign-in was cancelled or failed")}
              useOneTap={false}
            />
          </GoogleOAuthProvider>
        ) : (
          <p className="gate-hint">
            Set GOOGLE_CLIENT_ID in .env (Google Cloud Console → OAuth 2.0 Web client) and restart
            uvicorn.
          </p>
        )}
      </div>
    );
  }

  return (
    <>
      <header>
        <div>
          <h1>Horizon Trust knowledge assistant</h1>
          <p>
            Signed in with Google
            {sessionId ? ` · Session ${sessionId.slice(0, 8)}…` : " · New conversation"}
            {redisOn === null ? "" : redisOn ? " · Redis on" : " · Redis off"}
          </p>
        </div>
        <div className="auth">
          <span className="who">
            {me.username}
            <small>{me.roles.map(roleLabel).join(", ") || "no app roles"}</small>
          </span>
          {isManager ? (
            <button className="ghost" type="button" onClick={() => void reindex()}>
              Reindex
            </button>
          ) : null}
          <button className="ghost" type="button" onClick={newChat}>
            New chat
          </button>
          <button className="ghost" type="button" onClick={() => void signOut()}>
            Sign out
          </button>
        </div>
      </header>
      {cacheBanner ? <div className="banner">{cacheBanner}</div> : null}
      <div className="shell">
        <aside className="sidebar">
          <p className="sidebar-label">Your conversations</p>
          {conversations.length === 0 ? (
            <p className="sidebar-empty">None yet. Send a message to create one.</p>
          ) : (
            conversations.map((c) => (
              <button
                type="button"
                key={c.session_id}
                className={c.session_id === sessionId ? "convo active" : "convo"}
                onClick={() => void openConversation(c.session_id)}
              >
                <span>{c.title}</span>
                <small>{c.message_count} messages</small>
              </button>
            ))
          )}
        </aside>
        <div className="main">
          <div className="thread" ref={listRef}>
            {messages.length === 0 ? (
              <p style={{ color: "var(--muted)" }}>
                Ask a fund-doc question. Repeat it in this chat for a Redis hit. Managers (experts)
                listed in GOOGLE_MANAGER_EMAILS can reindex.
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
        </div>
      </div>
    </>
  );
}
