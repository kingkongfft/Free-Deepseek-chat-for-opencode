# AGENTS.md — DeepSeek API

## What this is
Unofficial OpenAI-compatible API bridge for chat.deepseek.com. Turns the free DeepSeek web chat into a local API server. No API keys — uses your browser session.

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
| Install deps | `pip install -r requirements.txt` |
| Install Playwright | `playwright install chromium` |
| Test health | `curl http://127.0.0.1:8000/healthz` |

## Architecture
- **`deepseek/`** — Core library: auth (Playwright), HTTP client, PoW solver (WASM)
- **`server/`** — FastAPI OpenAI-compatible server
- **`app.py`** — Entry point, runs uvicorn

## Critical quirks
1. **Session is browser-based** — first run opens Chrome for login. Session cached in `session/` (gitignored). Auto-refreshes for ~6 hours.
2. **PoW is serialized** — wasmtime store is not reentrant. All requests queue behind a lock. Don't hammer it.
3. **Tool calling uses prompt injection** — tools are injected into the prompt, model outputs `<tool_call>` blocks. Not native API support. Works better with `deepseek-chat` than `deepseek-expert` for vague prompts.
4. **Rate limit** — 30 req/min per IP by default (`RATE_LIMIT_PER_MINUTE` env var).
5. **Known models** — only `deepseek-chat` and `deepseek-expert` are accepted. Unknown models return 404.

## Env vars
| Var | Default | Purpose |
|-----|---------|---------|
| `HOST` | `127.0.0.1` | Server bind host |
| `PORT` | `8000` | Server port |
| `RATE_LIMIT_PER_MINUTE` | `30` | Per-IP rate limit |
| `DEEPSEEK_PROFILE_DIR` | `session/profile` | Reuse existing Chrome profile |
| `SERVER_INTERACTIVE_LOGIN` | `1` | Open browser on missing session |
| `DEEPSEEK_SESSION_ID` | _(none)_ | Pin all requests to one DeepSeek chat session (UUID from URL: `chat.deepseek.com/a/chat/s/<ID>`) |

## File structure
```
deepseek/
  auth.py       # Playwright login + session capture
  client.py     # HTTP client (chat, stream)
  pow.py        # PoW solver (wasmtime + sha3_wasm_bg.wasm)
server/
  api.py        # FastAPI endpoints
  config.py     # MODEL_MAP, rate limit, server settings
  openai_format.py  # Message formatting, tool call parsing
  schemas.py    # Pydantic request/response models
  ratelimit.py  # Sliding window rate limiter
```
