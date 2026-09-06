import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { UserManager } from "oidc-client-ts";
import {
  completeSignInIfNeeded,
  createUserManager,
  fetchMe,
  loadAuthConfig,
  type Me,
} from "./auth";

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

async function accessToken(mgr: UserManager): Promise<string | null> {
  let user = await mgr.getUser();
  if (!user) return null;
  if (user.expired) {
    try {
      user = await mgr.signinSilent();
    } catch {
      return null;
    }
  }
  return user?.access_token ?? null;
}

export default function App() {
  const mgrRef = useRef<UserManager | null>(null);
  const [ready, setReady] = useState(false);
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

  const isAdmin = Boolean(me?.roles.includes("admin"));

  const loadConversations = useCallback(async () => {
    const mgr = mgrRef.current;
    if (!mgr) return;
    const token = await accessToken(mgr);
    if (!token) {
      setConversations([]);
      return;
    }
    const res = await fetch("/v1/conversations", {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) return;
    const data = (await res.json()) as { conversations: ConvoSummary[] };
    setConversations(data.conversations);
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const cfg = await loadAuthConfig();
        const mgr = createUserManager(cfg);
        mgrRef.current = mgr;
        const user = await completeSignInIfNeeded(mgr);
        if (cancelled) return;
        if (user?.access_token) {
          const profile = await fetchMe(user.access_token);
          if (cancelled) return;
          setMe(profile);
          await loadConversations();
        }
      } catch (err) {
        if (!cancelled) {
          setAuthError(err instanceof Error ? err.message : "Sign-in failed");
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

  async function signIn() {
    const mgr = mgrRef.current;
    if (!mgr) return;
    await mgr.signinRedirect();
  }

  async function signOut() {
    const mgr = mgrRef.current;
    if (!mgr) return;
    await mgr.signoutRedirect();
  }

  async function openConversation(id: string) {
    const mgr = mgrRef.current;
    if (!mgr) return;
    const token = await accessToken(mgr);
    if (!token) return;
    const res = await fetch(`/v1/conversations/${id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) return;
    const data = (await res.json()) as { session_id: string; messages: ChatMessage[] };
    setSessionId(data.session_id);
    setMessages(data.messages);
    setCacheBanner(null);
  }

  async function reindex() {
    const mgr = mgrRef.current;
    if (!mgr) return;
    const token = await accessToken(mgr);
    if (!token) return;
    const res = await fetch("/v1/reindex", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.status === 403) {
      setCacheBanner("Reindex requires the admin role.");
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
    const mgr = mgrRef.current;
    if (!q || busy || !mgr) return;
    const token = await accessToken(mgr);
    if (!token) {
      setMessages((m) => [...m, { role: "assistant", content: "Session expired. Sign in again." }]);
      return;
    }
    setBusy(true);
    setCacheBanner(null);
    setMessages((m) => [...m, { role: "user", content: q }]);
    setDraft("");

    let res: Response;
    try {
      res = await fetch("/v1/chat", {
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
        { role: "assistant", content: "Could not reach the API. Is uvicorn running on port 8000?" },
      ]);
      setBusy(false);
      return;
    }
    if (res.status === 401) {
      setMessages((m) => [...m, { role: "assistant", content: "Token expired or invalid. Sign in again." }]);
      setBusy(false);
      return;
    }
    if (res.status === 403) {
      setMessages((m) => [
        ...m,
        { role: "assistant", content: "You do not have the analyst role required to chat." },
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
        <p>Sign in with the identity provider (Authorization Code + PKCE). Tokens are validated by the API via JWKS.</p>
        {authError ? <p className="gate-error">{authError}</p> : null}
        <button className="primary" type="button" onClick={() => void signIn()}>
          Sign in
        </button>
        <p className="gate-hint">
          Local Keycloak: analyst / analyst-pass · analyst2 / analyst-pass · admin / admin-pass
        </p>
      </div>
    );
  }

  return (
    <>
      <header>
        <div>
          <h1>Horizon Trust knowledge assistant</h1>
          <p>
            OIDC access token · conversations keyed by subject
            {sessionId ? ` · Session ${sessionId.slice(0, 8)}…` : " · New conversation"}
            {redisOn === null ? "" : redisOn ? " · Redis on" : " · Redis off"}
          </p>
        </div>
        <div className="auth">
          <span className="who">
            {me.username}
            <small>{me.roles.join(", ") || "no app roles"}</small>
          </span>
          {isAdmin ? (
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
                Ask a fund-doc question. Repeat it in this chat for a Redis hit. Sign in as analyst2 to
                confirm isolation. Only admin can reindex.
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
