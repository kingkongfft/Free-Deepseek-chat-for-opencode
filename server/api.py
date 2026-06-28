"""
OpenAI-compatible FastAPI server for DeepSeek.

Point any OpenAI client at http://localhost:8000/v1 :

    from openai import OpenAI
    client = OpenAI(base_url="http://localhost:8000/v1", api_key="not-needed")
    r = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": "Hello!"}],
    )

Endpoints:
    GET  /v1/models
    POST /v1/chat/completions   (stream=true supported)
    GET  /healthz

Requests under /v1 are rate limited per client IP (default 30/min, set via
RATE_LIMIT_PER_MINUTE); /healthz is exempt.
"""

from __future__ import annotations

import logging
import threading
import time

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from deepseek.auth import LoginRequired
from deepseek.client import DeepSeekClient

from .config import (
    DEEPSEEK_SESSION_ID,
    MODEL_MAP,
    RATE_LIMIT_PER_MINUTE,
    SERVER_INTERACTIVE_LOGIN,
    is_known_model,
    resolve_model_type,
)
from .openai_format import (
    completion_response,
    messages_to_prompt,
    stream_chunks,
    _parse_tool_calls,
)
from .ratelimit import RateLimiter, install_rate_limit
from .schemas import ChatCompletionRequest

load_dotenv()

app = FastAPI(title="DeepSeek OpenAI-compatible API", version="0.1.0")
install_rate_limit(app, RateLimiter(limit=RATE_LIMIT_PER_MINUTE, window=60.0))

_log = logging.getLogger(__name__)

# One shared client (and its signed-in session) built lazily on first use.
_client: DeepSeekClient | None = None
_client_lock = threading.Lock()


def get_client() -> DeepSeekClient:
    """Build (once) the shared client and its signed-in session.

    Session resolution: cached file → headless capture off the persistent
    profile. If neither works and SERVER_INTERACTIVE_LOGIN is on (the default),
    it opens a visible browser window so you can sign in — the triggering
    request blocks until you finish. If interactive login is off, it raises
    `LoginRequired`, which the endpoint turns into an actionable 503.

    This touches Playwright's sync API, so callers must invoke it OFF the event
    loop (via run_in_threadpool); calling it inside the asyncio loop raises
    "Playwright Sync API inside the asyncio loop"."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = DeepSeekClient(allow_interactive=SERVER_INTERACTIVE_LOGIN)
    return _client


def _error(message: str, status: int = 500, err_type: str = "server_error"):
    return JSONResponse(
        status_code=status,
        content={"error": {"message": message, "type": err_type}},
    )


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/v1/models")
def list_models():
    created = int(time.time())
    return {
        "object": "list",
        "data": [
            {"id": name, "object": "model", "created": created, "owned_by": "deepseek"}
            for name in MODEL_MAP
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest):
    if not req.messages:
        return _error(
            "`messages` must not be empty", status=400, err_type="invalid_request_error"
        )

    # Debug: log incoming tool names so we can verify opencode's tool definitions
    if req.tools:
        tool_names = [t.function.name for t in req.tools]
        _log.debug("Incoming tools: %s", tool_names)

    if not is_known_model(req.model):
        return _error(
            f"The model `{req.model}` does not exist. Available models: "
            f"{', '.join(MODEL_MAP)}",
            status=404,
            err_type="model_not_found",
        )

    # A thread's model is fixed when it's created, so on resume we ignore `model`
    # (the OpenAI SDK always sends one) and let the existing thread's model stand.
    #
    # If DEEPSEEK_SESSION_ID is set, pin every request to that session so all
    # turns appear in the same DeepSeek UI chat. The client's own conversation_id
    # (from a previous response) takes precedence — it already encodes the right
    # session + parent message for multi-turn threading.
    #
    # IMPORTANT: opencode does NOT echo conversation_id back on continuation turns
    # (it's not an OpenAI standard field). So every turn is a fresh DeepSeek call
    # with the full message history reconstructed into `prompt`. We therefore never
    # resume a DeepSeek thread mid-conversation — each request is self-contained.
    # DEEPSEEK_SESSION_ID only pins which chat *session* new messages land in.
    is_continuation = any(m.role == "tool" for m in req.messages) or (
        sum(1 for m in req.messages if m.role == "assistant") > 0
        and req.messages[-1].role != "user"
    )
    effective_cid = req.conversation_id or (
        DEEPSEEK_SESSION_ID if (DEEPSEEK_SESSION_ID and not is_continuation) else None
    )
    model_type = None if effective_cid else resolve_model_type(req.model)
    prompt, has_tools, files_inlined = messages_to_prompt(req.messages, tools=req.tools)

    # Dump continuation prompt to file for debugging tool result handling
    # Always dump every request for debugging
    try:
        import json as _json, os as _os

        _base = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        with open(
            _os.path.join(_base, "debug_request.json"), "w", encoding="utf-8"
        ) as _f:
            _f.write(
                _json.dumps(
                    {
                        "messages": [
                            _m.model_dump(exclude_none=True) for _m in req.messages
                        ],
                        "has_tools": bool(req.tools),
                        "prompt": prompt,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
    except Exception:
        pass

    if req.tools and any(m.role == "tool" for m in req.messages):
        try:
            import json as _json

            with open("debug_continuation.txt", "w", encoding="utf-8") as _f:
                _f.write("=== MESSAGES ===\n")
                for _m in req.messages:
                    _f.write(
                        _json.dumps(_m.model_dump(exclude_none=True), indent=2) + "\n"
                    )
                _f.write("\n=== PROMPT SENT TO DEEPSEEK ===\n")
                _f.write(prompt)
        except Exception:
            pass

    try:
        # Off the event loop: get_client() uses Playwright's sync API, which
        # errors if run inside the asyncio loop.
        client = await run_in_threadpool(get_client)
    except LoginRequired as e:
        return _error(str(e), status=503, err_type="login_required")
    except Exception as e:  # session/login failure
        return _error(f"Failed to initialise DeepSeek session: {e}")

    if req.stream:

        def gen():
            stream = client.stream(
                prompt,
                conversation_id=effective_cid,
                model=model_type,
                thinking=req.thinking,
                search=req.search,
            )
            yield from stream_chunks(
                req.model, stream, tools=None if files_inlined else req.tools
            )

        return StreamingResponse(gen(), media_type="text/event-stream")

    try:
        reply = await run_in_threadpool(
            client.chat,
            prompt,
            effective_cid,
            model_type,
            req.thinking,
            req.search,
        )
    except Exception as e:
        return _error(f"DeepSeek request failed: {e}")

    # Parse tool calls from the response if tools were provided.
    # Skip when files were inlined (@mention) — the model answers directly,
    # any tool-call-shaped text in the response is a hallucination, not a real call.
    tool_calls = None
    content = reply.text
    if req.tools and not files_inlined:
        content, tool_calls = _parse_tool_calls(reply.text, tools=req.tools)
        if not tool_calls:
            _log.warning(
                "Tool call expected but model returned plain text. "
                "Model may have narrated instead of using <tool_call> tags. "
                "Response: %.200s",
                content,
            )

    return completion_response(
        req.model,
        content,
        prompt,
        reply.conversation_id,
        tool_calls=tool_calls,
    )
