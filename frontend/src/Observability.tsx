import { useMemo, useState } from "react";

export type IngestLive = {
  active: boolean;
  trace_id: string;
  actor: string;
  stage: string;
  source_key: string;
  files_total: number;
  files_changed: number;
  files_reused: number;
  files_done: number;
  files_failed: number;
  last_error: string;
  started_at: string;
  updated_at: string;
};

export type IngestEvent = {
  ts: string;
  trace_id: string;
  stage: string;
  status: string;
  source_key: string;
  detail: string;
  chunks: number;
  duration_ms: number;
  files_done: number;
  files_total: number;
  strategy?: string;
  suffix?: string;
  pages?: number;
  chunk_chars_min?: number;
  chunk_chars_avg?: number;
  chunk_chars_max?: number;
};

export type IngestRun = {
  run_id: string;
  started_at: string | null;
  actor: string;
  status: string;
  files_rechunked: number;
  files_reused: number;
  chunks_indexed: number;
  error_detail: string | null;
  index_version: string;
};

export type IngestDocument = {
  source_key: string;
  trace_id: string;
  stage: string;
  status: string;
  strategy: string;
  suffix: string;
  chunks: number;
  pages: number;
  duration_ms: number;
  chunk_chars_min: number;
  chunk_chars_avg: number;
  chunk_chars_max: number;
  events: IngestEvent[];
};

export type LogRow = {
  ts?: string;
  level?: string;
  logger?: string;
  msg?: string;
  stage?: string;
  ingest_trace_id?: string;
  source_key?: string;
  strategy?: string;
  chunks?: number;
  exc?: string;
};

export type IngestStatus = {
  live: IngestLive;
  events: IngestEvent[];
  documents?: IngestDocument[];
  errors?: IngestEvent[];
  logs?: LogRow[];
  trace_ids?: string[];
  docs_indexed: number;
  index_version: string;
  ingesting: boolean;
  runs: IngestRun[];
};

type KnowledgeChunk = {
  file_id: string;
  text: string;
  strategy?: string;
  section?: string;
  page?: string;
};

type Props = {
  status: IngestStatus;
  chunkFile: string;
  fileOptions: { file_id: string; chunks: number }[];
  chunkSample: KnowledgeChunk[];
  onChunkFile: (fileId: string) => void;
  onLoadChunks: (fileId: string) => void;
};

export default function Observability({
  status,
  chunkFile,
  fileOptions,
  chunkSample,
  onChunkFile,
  onLoadChunks,
}: Props) {
  const [traceFilter, setTraceFilter] = useState("");
  const [errorsOnly, setErrorsOnly] = useState(false);
  const [selectedDoc, setSelectedDoc] = useState("");

  const live = status.live;
  const documents = status.documents ?? [];
  const selected = documents.find((d) => d.source_key === selectedDoc) || documents[0];

  const events = useMemo(() => {
    let rows = status.events ?? [];
    if (traceFilter) rows = rows.filter((e) => e.trace_id === traceFilter);
    if (selectedDoc) rows = rows.filter((e) => !e.source_key || e.source_key === selectedDoc);
    if (errorsOnly) rows = rows.filter((e) => e.status === "error");
    return rows;
  }, [status.events, traceFilter, selectedDoc, errorsOnly]);

  const logs = useMemo(() => {
    let rows = status.logs ?? [];
    if (traceFilter) rows = rows.filter((row) => row.ingest_trace_id === traceFilter);
    if (selectedDoc) rows = rows.filter((row) => !row.source_key || row.source_key === selectedDoc);
    if (errorsOnly) rows = rows.filter((row) => (row.level || "").toUpperCase() === "ERROR");
    return rows;
  }, [status.logs, traceFilter, selectedDoc, errorsOnly]);

  return (
    <div className="obs">
      <div className="obs-kpis">
        <div>
          <label>Status</label>
          <strong>{status.ingesting ? "INGESTING" : live.stage || "idle"}</strong>
        </div>
        <div>
          <label>Trace</label>
          <strong className="mono">{live.trace_id || "—"}</strong>
        </div>
        <div>
          <label>Current doc</label>
          <strong>{live.source_key || "—"}</strong>
        </div>
        <div>
          <label>Files</label>
          <strong>
            {live.files_done}/{live.files_changed || live.files_total} · failed {live.files_failed}
          </strong>
        </div>
        <div>
          <label>Vespa chunks</label>
          <strong>{status.docs_indexed}</strong>
        </div>
      </div>
      {live.last_error ? <div className="obs-error">{live.last_error}</div> : null}

      <div className="obs-filters">
        <select value={traceFilter} onChange={(e) => setTraceFilter(e.target.value)}>
          <option value="">All traces</option>
          {(status.trace_ids || []).map((id) => (
            <option key={id} value={id}>
              {id}
            </option>
          ))}
        </select>
        <label className="obs-check">
          <input type="checkbox" checked={errorsOnly} onChange={(e) => setErrorsOnly(e.target.checked)} />
          Errors only
        </label>
      </div>

      <div className="obs-grid">
        <section>
          <h2>Documents being processed</h2>
          <p className="obs-hint">Click a file to see chunking strategy, sizes, and stages.</p>
          <ul className="obs-docs">
            {documents.length === 0 ? <li className="muted">No file events yet. Wait for ingest.</li> : null}
            {documents.map((doc) => (
              <li key={doc.source_key}>
                <button
                  type="button"
                  className={selected?.source_key === doc.source_key ? "active" : ""}
                  onClick={() => {
                    setSelectedDoc(doc.source_key);
                    onChunkFile(doc.source_key.replace(/\.[^.]+$/, ""));
                  }}
                >
                  <span className="obs-doc-name">{doc.source_key}</span>
                  <span className="muted">
                    {doc.stage}
                    {doc.strategy ? ` · ${doc.strategy}` : ""}
                    {doc.chunks ? ` · ${doc.chunks} chunks` : ""}
                    {doc.pages ? ` · ${doc.pages} pages` : ""}
                    {doc.status === "error" ? " · ERROR" : ""}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>

        <section>
          <h2>Chunking for {selected?.source_key || "—"}</h2>
          {selected ? (
            <dl className="obs-dl">
              <dt>Stage</dt>
              <dd>
                {selected.stage} ({selected.status})
              </dd>
              <dt>Strategy</dt>
              <dd>{selected.strategy || "not chunked yet"}</dd>
              <dt>Chunks / pages</dt>
              <dd>
                {selected.chunks} / {selected.pages}
              </dd>
              <dt>Chunk chars min/avg/max</dt>
              <dd>
                {selected.chunk_chars_min}/{selected.chunk_chars_avg}/{selected.chunk_chars_max}
              </dd>
              <dt>Duration</dt>
              <dd>{selected.duration_ms} ms</dd>
              <dt>Trace</dt>
              <dd className="mono">{selected.trace_id}</dd>
            </dl>
          ) : (
            <p className="muted">No document selected.</p>
          )}
          <h3>Stored chunk text</h3>
          <button className="ghost" type="button" onClick={() => onLoadChunks(chunkFile)}>
            Load chunks
          </button>
          {fileOptions.length > 0 ? (
            <select
              className="ingest-select"
              value={chunkFile}
              onChange={(e) => {
                onChunkFile(e.target.value);
                onLoadChunks(e.target.value);
              }}
            >
              <option value="">All files</option>
              {fileOptions.map((f) => (
                <option key={f.file_id} value={f.file_id}>
                  {f.file_id} ({f.chunks})
                </option>
              ))}
            </select>
          ) : null}
          {chunkSample.map((c, i) => (
            <div className="chunk-sample" key={`${c.file_id}-${i}`}>
              <strong>
                {c.file_id}
                {c.strategy ? ` · ${c.strategy}` : ""}
                {c.page ? ` · p.${c.page}` : ""}
                {c.section ? ` · ${c.section}` : ""}
              </strong>
              <pre>{c.text.slice(0, 800)}</pre>
            </div>
          ))}
        </section>
      </div>

      <div className="obs-grid">
        <section>
          <h2>Trace events</h2>
          <ol className="obs-log">
            {events.map((ev, i) => (
              <li key={`${ev.ts}-${ev.stage}-${i}`} className={ev.status === "error" ? "err" : ""}>
                <time>{ev.ts?.slice(11, 19)}</time>
                <b>{ev.stage}</b>
                <span>{ev.source_key || "—"}</span>
                {ev.strategy ? <em>{ev.strategy}</em> : null}
                {ev.chunks ? <em>{ev.chunks} chunks</em> : null}
                {ev.detail ? <em>{ev.detail}</em> : null}
              </li>
            ))}
          </ol>
        </section>
        <section>
          <h2>Logs</h2>
          <ol className="obs-log">
            {logs.map((row, i) => (
              <li key={`${row.ts}-${i}`} className={(row.level || "") === "ERROR" ? "err" : ""}>
                <time>{String(row.ts || "").slice(11, 19)}</time>
                <b>{row.level}</b>
                <span>{row.source_key || row.stage || row.logger}</span>
                <em>{row.msg}</em>
                {row.exc ? <pre>{row.exc}</pre> : null}
              </li>
            ))}
          </ol>
        </section>
      </div>

      {(status.errors || []).length > 0 ? (
        <section>
          <h2>Errors</h2>
          <ul className="obs-log">
            {(status.errors || []).map((err, i) => (
              <li key={`${err.ts}-${i}`} className="err">
                <span>{err.source_key || err.stage}</span>
                <em>{err.detail}</em>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {status.runs.length > 0 ? (
        <section>
          <h2>Persisted ingest runs</h2>
          <ul className="obs-log">
            {status.runs.map((run) => (
              <li key={run.run_id}>
                <b>{run.status}</b>
                <span>{run.started_at}</span>
                <em>
                  {run.chunks_indexed} chunks · rechunked {run.files_rechunked} · {run.actor}
                </em>
                {run.error_detail ? <em className="err">{run.error_detail}</em> : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
