from __future__ import annotations

import hashlib
import json
import os
import uuid
from contextlib import asynccontextmanager

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent import generate_answer
from app.ingest import ingest_knowledge
from app.models import Conversation, Message

_root = Path(__file__).resolve().parents[2]
load_dotenv(_root / ".env")
load_dotenv()

conversations: dict[str, Conversation] = {}
answer_cache: dict[str, tuple[str, list[dict]]] = {}
chunks = []
index = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global chunks, index
    chunks, index = ingest_knowledge()
    yield


app = FastAPI(title="Fintech AI MVP", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    session_id: str | None = None


def _norm(q: str) -> str:
    return " ".join(q.lower().split())


def _cache_key(session_id: str, message: str) -> str:
    return hashlib.sha256(f"{session_id}|{_norm(message)}".encode()).hexdigest()


@app.get("/health")
def health():
    return {
        "ok": True,
        "docs_indexed": len(chunks),
        "llm_enabled": bool(os.getenv("LLM_API_KEY", "").strip()),
        "conversations": len(conversations),
    }


@app.get("/v1/conversations/{session_id}")
def get_conversation(session_id: str):
    conv = conversations.get(session_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return {
        "session_id": conv.session_id,
        "title": conv.title,
        "messages": [m.__dict__ for m in conv.messages],
    }


@app.post("/v1/chat")
async def chat(body: ChatRequest):
    if index is None:
        raise HTTPException(503, "Index not ready")

    text = body.message.strip()
    if not text:
        raise HTTPException(400, "Empty query")

    new_session = not body.session_id
    if new_session:
        session_id = str(uuid.uuid4())
        conv = Conversation(session_id=session_id, title=text[:60])
        conversations[session_id] = conv
    else:
        session_id = body.session_id
        conv = conversations.get(session_id)
        if not conv:
            raise HTTPException(404, "Conversation not found. Start a new chat.")

    cache_key = _cache_key(session_id, text)
    cached = answer_cache.get(cache_key)

    async def events():
        yield _sse({"type": "session", "session_id": session_id, "new_conversation": new_session})

        if cached:
            answer, citations = cached
            conv.messages.append(Message(role="user", content=text))
            conv.messages.append(
                Message(role="assistant", content=answer, citations=citations, cache_hit=True)
            )
            yield _sse({"type": "cache_hit", "value": True})
            yield _sse({"type": "token", "text": answer})
            yield _sse({"type": "citations", "citations": citations})
            yield _sse({"type": "done", "session_id": session_id, "cache_hit": True})
            return

        yield _sse({"type": "cache_hit", "value": False})
        conv.messages.append(Message(role="user", content=text))
        answer, citations, used_llm = await generate_answer(text, index)
        conv.messages.append(Message(role="assistant", content=answer, citations=citations))
        answer_cache[cache_key] = (answer, citations)
        yield _sse({"type": "token", "text": answer})
        yield _sse({"type": "citations", "citations": citations})
        yield _sse(
            {
                "type": "done",
                "session_id": session_id,
                "cache_hit": False,
                "used_llm": used_llm,
            }
        )

    return StreamingResponse(events(), media_type="text/event-stream")


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"
