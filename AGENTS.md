# AGENTS.md — DeepSeek API

Free DeepSeek web chat → OpenAI-compatible API. No API keys — uses your browser session.

## Quick start
```bash
python -m venv venv && venv\Scripts\activate  # Windows PowerShell
pip install -r requirements.txt
playwright install chromium
python -m deepseek.auth   # sign in once (opens browser)
python app.py             # http://127.0.0.1:8000
```

## Key commands
| Task | Command |
|------|---------|
| Start server | `python app.py` |
| Sign in (browser) | `python -m deepseek.auth` |
| Examples | `python examples/01_direct_chat.py` (from project root) |
| Debug logging | `$env:LOG_LEVEL="DEBUG"; python app.py` |
| Health check | `curl http://127.0.0.1:8000/healthz` |

## Critical quirks
1. **Session is browser-based** — Chrome opens for first login. Session cached in `session/` (gitignored). Auto-refreshes for ~6 hours.
2. **PoW is serialized** — wasmtime Store is not reentrant. All requests queue behind a lock (`_pow_lock`). Don't hammer it.
3. **Tool calling uses prompt injection** — tools injected into prompt, model outputs `<tool_call>` blocks. Parser handles 7 output variants (see `TOOL_CALLING_IMPROVEMENTS.md`). Two common failure modes: (a) model outputs fenced JSON `` ```json `` instead of `<tool_call>`, (b) model narrates "I'll do X" with no XML at all — unrecoverable without retry.
4. **`deepseek-chat` >> `deepseek-expert` for tool calling** — Expert narrates or outputs fenced JSON much more often, especially on continuation turns. Only use expert for pure reasoning, never for agentic multi-step tasks.
5. **Continuation turns are unreliable** — when a tool result is returned, the model often says "Done" instead of calling the next tool. Workaround: chain multi-step operations into one `&&` bash command to avoid continuation turns entirely.
6. **Rate limit** — 30 req/min per IP by default (`RATE_LIMIT_PER_MINUTE`). Over-limit gets 429 with `Retry-After`.
7. **Known models** — only `deepseek-chat` (Instant) and `deepseek-expert` (Expert). Unknown models return 404.
8. **`temperature`, `top_p`, `max_tokens` accepted but silently ignored** — DeepSeek's web API doesn't expose these.
9. **Usage counts are rough** — `~4 chars/token` estimate. No real token counts from DeepSeek.
10. **Continuation debugging** — `debug_continuation.txt` written on tool-result turns (full messages + prompt).

## Conversation model
- `conversation_id` format: `<session_uuid>:<message_id>` from DeepSeek's internal API.
- `DEEPSEEK_SESSION_ID` pins all requests to one existing chat session (UUID from `chat.deepseek.com/a/chat/s/<UUID>`). Without it, a new chat is created per request.
- opencode does **not** echo `conversation_id` back — every turn is self-contained with full message history. `is_continuation` is detected from tool/assistant roles in `messages`.
- `thinking` (DeepThink) and `search` (web search) are per-request booleans passed via `extra_body` — independent of model choice.

## Architecture
- **`deepseek/`** — Core library: auth (Playwright), HTTP client (httpx), PoW solver (wasmtime)
- **`server/`** — FastAPI OpenAI-compatible server
- **`app.py`** — Entry point, loads `.env` via `python-dotenv`, runs uvicorn
- **Playwright sync API** used for auth — must run off the asyncio event loop (uses `run_in_threadpool` in server)

## Env vars
| Var | Default | Purpose |
|-----|---------|---------|
| `HOST` | `127.0.0.1` | Server bind host |
| `PORT` | `8000` | Server port |
| `RATE_LIMIT_PER_MINUTE` | `30` | Per-IP rate limit on `/v1` endpoints |
| `DEEPSEEK_PROFILE_DIR` | `session/profile` | Reuse existing Chrome profile |
| `SERVER_INTERACTIVE_LOGIN` | `1` | Open browser on missing session (set `0` for headless) |
| `DEEPSEEK_SESSION_ID` | _(none)_ | Pin all requests to one DeepSeek chat session |
| `LOG_LEVEL` | _(none, default INFO)_ | Set to `DEBUG` for verbose logging |

## File structure
```
deepseek/
  auth.py       # Playwright login + session capture (sync API)
  client.py     # HTTP client: chat, stream, PoW challenge, SSE parser
  pow.py        # PoW solver via wasmtime + sha3_wasm_bg.wasm (serialized)
server/
  api.py        # FastAPI endpoints: /v1/chat/completions, /v1/models, /healthz
  config.py     # MODEL_MAP (deepseek-chat → default, deepseek-expert → expert), rate limit, env vars
  openai_format.py  # Message→prompt formatting, multi-format tool call parser (6 formats incl. fenced shell block)
  schemas.py    # Pydantic models: ChatCompletionRequest, Tool, ToolChoice, ChatMessage
  ratelimit.py  # Sliding-window per-IP rate limiter
```
