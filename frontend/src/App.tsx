import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { GoogleLogin, GoogleOAuthProvider } from "@react-oauth/google";
import { apiFetch, fetchMe, loadAuthConfig, signInWithGoogleIdToken, signOut as apiSignOut, type Me } from "./auth";
import Observability, { type IngestStatus } from "./Observability";

type Citation = {
  file_id: string;
  title: string;
  as_of: string;
  section?: string;
  page?: string;
  score: number;
  snippet: string;
};

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  cache_hit?: boolean;
  intent?: string;
  hitl_pending?: boolean;
};

type ConvoSummary = {
  session_id: string;
  title: string;
  message_count: number;
};

const HINTS = [
  "What is the KYC client onboarding procedure?",
  "What does the payment operations standard operating procedure cover at Horizon Trust?",
  "Summarize the Q2 2026 liquidity risk report.",
  "I am furious and want to file a complaint with a manager",
];

type KnowledgeChunk = {
  file_id: string;
  text: string;
  strategy?: string;
  section?: string;
  page?: string;
};

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
  const [indexBanner, setIndexBanner] = useState<string | null>(null);
  const [ingestStatus, setIngestStatus] = useState<IngestStatus | null>(null);
  const [chunkFile, setChunkFile] = useState("");
  const [chunkSample, setChunkSample] = useState<KnowledgeChunk[]>([]);
  const [fileOptions, setFileOptions] = useState<{ file_id: string; chunks: number }[]>([]);
  const [page, setPage] = useState<"chat" | "obs">("chat");
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

  useEffect(() => {
    if (!isManager) {
      setIngestStatus(null);
      return;
    }
    let cancelled = false;
    async function pollIngest() {
      try {
        const res = await apiFetch("/v1/ingest/status");
        if (!res.ok || cancelled) return;
        setIngestStatus((await res.json()) as IngestStatus);
      } catch {
        /* API still starting */
      }
    }
    void pollIngest();
    const id = window.setInterval(() => void pollIngest(), 1000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [isManager]);

  async function loadChunkSample(fileId: string) {
    const q = fileId ? `?file_id=${encodeURIComponent(fileId)}&limit=8` : "?limit=8";
    const res = await apiFetch(`/v1/knowledge${q}`);
    if (!res.ok) return;
    const data = (await res.json()) as {
      files?: { file_id: string; chunks: number }[];
      chunks?: KnowledgeChunk[];
    };
    setFileOptions(data.files ?? []);
    setChunkSample(data.chunks ?? []);
  }

  useEffect(() => {
    let cancelled = false;
    async function pollHealth() {
      try {
        const res = await fetch("/health", { signal: AbortSignal.timeout(5000) });
        if (!res.ok) return;
        const data = (await res.json()) as {
          ingesting?: boolean;
          docs_indexed?: number;
          vespa?: boolean;
          ingest_in_api?: boolean;
          ingest_stage?: string;
          ingest_source_key?: string;
          ingest_files_done?: number;
          ingest_files_total?: number;
        };
        if (!cancelled) {
          if (data.ingesting) {
            const file = data.ingest_source_key ? ` ${data.ingest_source_key}` : "";
            const progress =
              data.ingest_files_total && data.ingest_files_total > 0
                ? ` (${data.ingest_files_done ?? 0}/${data.ingest_files_total})`
                : "";
            const stage = data.ingest_stage ? ` · ${data.ingest_stage}` : "";
            setIndexBanner(`Indexing${file}${progress}${stage}. Chat works after chunks are in Vespa.`);
          } else if (data.vespa === false) {
            setIndexBanner(
              "Vespa search (port 8080) is down. Config 19071 can be up while 8080 stays empty until ingest deploys the app.",
            );
          } else if ((data.docs_indexed ?? 0) === 0) {
            setIndexBanner(
              data.ingest_in_api
                ? "Vespa has no chunks yet. Wait for the ingest logs in uvicorn."
                : "Vespa has no chunks. This API is not ingesting (INGEST_IN_API=false). Run python -m app.worker.ingest or set INGEST_IN_API=true and restart uvicorn.",
            );
          } else {
            setIndexBanner(null);
          }
        }
      } catch {
        /* API still starting */
      }
    }
    void pollHealth();
    const id = window.setInterval(() => void pollHealth(), 4000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

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
      const body = (await res.json().catch(() => ({}))) as { detail?: string };
      setCacheBanner(body.detail || `Reindex failed (${res.status}).`);
      return;
    }
    const data = (await res.json()) as {
      queued?: boolean;
      index_version?: string;
      flushed_keys?: number;
      detail?: string;
    };
    if (data.queued) {
      setCacheBanner(data.detail || "Reindex queued for the ingest worker.");
      return;
    }
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
    if (res.status === 400) {
      const body = (await res.json().catch(() => ({}))) as { detail?: string };
      setMessages((m) => [
        ...m,
        { role: "assistant", content: body.detail || "That question could not be searched." },
      ]);
      setBusy(false);
      return;
    }
    if (res.status === 503) {
      const body = (await res.json().catch(() => ({}))) as { detail?: string };
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: body.detail || "Knowledge is still indexing in the background. Try again in a minute.",
        },
      ]);
      setBusy(false);
      return;
    }
    if (!res.ok || !res.body) {
      const body = (await res.json().catch(() => ({}))) as { detail?: string };
      setMessages((m) => [
        ...m,
        { role: "assistant", content: body.detail || `Request failed (${res.status}).` },
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
    let intent = "";
    let hitlPending = false;

    const applyEvent = (ev: Record<string, unknown>) => {
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
      if (ev.type === "done") {
        if (typeof ev.intent === "string") intent = ev.intent;
        if (ev.hitl_pending) hitlPending = true;
      }
    };

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop() ?? "";
      for (const part of parts) {
        const line = part.replace(/^data:\s*/, "");
        if (!line) continue;
        try {
          applyEvent(JSON.parse(line) as Record<string, unknown>);
        } catch {
          continue;
        }
      }
    }
    if (buf.trim()) {
      const line = buf.replace(/^data:\s*/, "");
      try {
        applyEvent(JSON.parse(line) as Record<string, unknown>);
      } catch {
        /* incomplete trailer */
      }
    }

    setMessages((m) => [
      ...m,
      {
        role: "assistant",
        content: assistant || "No answer came back.",
        citations,
        cache_hit: hit,
        intent: intent || undefined,
        hitl_pending: hitlPending || undefined,
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
        {indexBanner ? <p className="gate-hint">{indexBanner}</p> : null}
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
            <>
              <button
                className="ghost"
                type="button"
                onClick={() => setPage((p) => (p === "obs" ? "chat" : "obs"))}
              >
                {page === "obs" ? "Chat" : "Observability"}
              </button>
              <button className="ghost" type="button" onClick={() => void reindex()}>
                Reindex
              </button>
            </>
          ) : null}
          <button className="ghost" type="button" onClick={newChat}>
            New chat
          </button>
          <button className="ghost" type="button" onClick={() => void signOut()}>
            Sign out
          </button>
        </div>
      </header>
      {indexBanner ? <div className="banner">{indexBanner}</div> : null}
      {cacheBanner ? <div className="banner">{cacheBanner}</div> : null}
      {isManager && page === "obs" ? (
        ingestStatus ? (
          <Observability
            status={ingestStatus}
            chunkFile={chunkFile}
            fileOptions={fileOptions}
            chunkSample={chunkSample}
            onChunkFile={setChunkFile}
            onLoadChunks={(id) => void loadChunkSample(id)}
          />
        ) : (
          <p className="obs-hint" style={{ padding: 20 }}>
            Loading observability from GET /v1/ingest/status …
          </p>
        )
      ) : (
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
                  Ask about the Northstar knowledge corpus. S3 files are chunked in the background.
                </p>
              ) : null}
              {messages.map((m, i) => (
                <div className={`bubble ${m.role}`} key={i}>
                  <div className="body">{m.content}</div>
                  {m.intent || m.hitl_pending ? (
                    <div className="bubble-meta">
                      {m.intent ? `intent: ${m.intent}` : ""}
                      {m.hitl_pending ? " · waiting for a manager" : ""}
                    </div>
                  ) : null}
                  {m.citations && m.citations.length > 0 ? (
                    <div className="cites">
                      {m.citations.map((c) => (
                        <div className="cite" key={c.file_id + c.snippet.slice(0, 12)}>
                          <strong>{c.file_id}</strong> · {c.title} · {c.as_of}
                          {c.section ? ` · ${c.section}` : ""} · score {c.score}
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
      )}
    </>
  );
}
