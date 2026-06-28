# DeepSeek API: free DeepSeek for opencode and any OpenAI-compatible client

**Using your own DeepSeek account.** No API key, no credits, no paid plan — turns the free chat at [chat.deepseek.com](https://chat.deepseek.com) into a local API server you can wire into [opencode](https://opencode.ai), Cursor, Continue, or any OpenAI-compatible tool.

This fork adds full **tool calling support** so AI coding agents like opencode can run their complete workflow — reading and writing files, running shell commands, building skills, and more — entirely through the free DeepSeek web interface.

> **Unofficial project.** Not affiliated with or endorsed by DeepSeek. Automates the consumer DeepSeek web experience for personal use — use responsibly and within DeepSeek's terms.

---

## What this fork adds

The original [sums001/Deepseek-API](https://github.com/sums001/Deepseek-API) provides the core bridge (auth, PoW solver, HTTP client, FastAPI server). This fork adds:

| Feature | Detail |
|---|---|
| **Tool / function calling** | Full OpenAI-compatible `tools` field — definitions injected via prompt, model output parsed into `tool_calls` response |
| **Multi-format parser** | Handles 4 output variants DeepSeek produces: standard JSON, named-attribute XML, Anthropic `<invoke>` XML (parallel calls), and direct tool-name tags |
| **opencode compatibility** | All 9 opencode built-in tools (`bash`, `read`, `write`, `edit`, `glob`, `grep`, `webfetch`, `todowrite`, `task`) tested and working |
| **Session pinning** | `DEEPSEEK_SESSION_ID` env var pins all requests to one existing chat — no new chat created per prompt |
| **Streaming tool calls** | Tool calls are buffered and streamed in OpenAI SSE format with correct `finish_reason: "tool_calls"` |

---

## opencode quick start

**1. Start the server**

```powershell
git clone https://github.com/kingkongfft/Deepseek-API
cd Deepseek-API
python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
python -m deepseek.auth        # sign in once — browser opens
python app.py                  # server at http://127.0.0.1:8000
```

**2. Configure opencode** — add to your `opencode.json`:

```json
{
  "provider": {
    "deepseek-local": {
      "name": "DeepSeek Local (Free)",
      "npm": "@ai-sdk/openai-compatible",
      "options": {
        "baseURL": "http://127.0.0.1:8000/v1",
        "apiKey": "unused"
      },
      "models": {
        "deepseek-chat": {
          "name": "DeepSeek Chat (Local)",
          "limit": { "context": 65536, "output": 8192 }
        },
        "deepseek-expert": {
          "name": "DeepSeek Expert (Local)",
          "limit": { "context": 65536, "output": 8192 }
        }
      }
    }
  }
}
```

**3. (Optional) Pin to a single chat session** so all turns appear in one DeepSeek UI thread:

```powershell
# Copy the UUID from: https://chat.deepseek.com/a/chat/s/<UUID>
$env:DEEPSEEK_SESSION_ID="your-session-uuid-here"
python app.py
```

---

## Tool calling

Tool definitions sent in the `tools` field are injected into the prompt. The model's output is parsed for tool calls and returned in standard OpenAI format. The parser handles every output variant DeepSeek produces:

| Format | Example |
|---|---|
| Standard JSON | `<tool_call>{"name": "bash", "arguments": {"command": "ls"}}</tool_call>` |
| Named attribute | `<tool_call name="bash">{"command": "ls"}</tool_call>` |
| Anthropic XML | `<tool_calls><invoke name="bash"><parameter name="command">ls</parameter></invoke></tool_calls>` |
| Direct tag | `<bash>{"command": "ls"}</bash>` |

Multiple parallel tool calls in one response (Anthropic XML format) are fully supported.

### opencode tool names (confirmed from binary analysis)

| Tool | Required params | Optional params |
|---|---|---|
| `bash` | `command` | `timeout`, `workdir` |
| `read` | `filePath` | `offset`, `limit` |
| `write` | `filePath`, `content` | — |
| `edit` | `filePath`, `oldString`, `newString` | `replaceAll` |
| `glob` | `pattern` | `path` |
| `grep` | `pattern` | `path`, `include` |
| `webfetch` | `url` | `format` |
| `todowrite` | `todos` | — |
| `task` | `description`, `prompt`, `subagent_type` | `task_id` |

See [TOOL_CALLING_IMPROVEMENTS.md](TOOL_CALLING_IMPROVEMENTS.md) for full technical detail.

---

## General usage

### As a Python library

```python
from deepseek import DeepSeekClient

client = DeepSeekClient()
reply = client.chat("Say hello in one short sentence.")
print(reply.text)

# Continue the same conversation
reply2 = client.chat("And now in French?", conversation_id=reply.conversation_id)
print(reply2.text)

# Stream token by token
for chunk in client.stream("Tell me a short joke"):
    print(chunk, end="", flush=True)
```

### As an OpenAI-compatible server

```bash
python app.py
# -> http://127.0.0.1:8000/v1
```

```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:8000/v1", api_key="unused")
resp = client.chat.completions.create(
    model="deepseek-chat",
    messages=[{"role": "user", "content": "Hello!"}],
)
print(resp.choices[0].message.content)
```

**Endpoints**

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/chat/completions` | Chat — supports `stream`, `tools`, `conversation_id`, `thinking`, `search` |
| `GET` | `/v1/models` | List available models |
| `GET` | `/healthz` | Health check |

---

## Environment variables

| Var | Default | Purpose |
|---|---|---|
| `HOST` | `127.0.0.1` | Server bind host |
| `PORT` | `8000` | Server port |
| `RATE_LIMIT_PER_MINUTE` | `30` | Per-IP rate limit |
| `DEEPSEEK_SESSION_ID` | _(none)_ | Pin all requests to one chat session (UUID from `chat.deepseek.com/a/chat/s/<ID>`) |
| `SERVER_INTERACTIVE_LOGIN` | `1` | Open browser automatically on missing session |
| `DEEPSEEK_PROFILE_DIR` | `session/profile` | Chrome profile directory for session reuse |

---

## Models

| Model name | DeepSeek mode | Notes |
|---|---|---|
| `deepseek-chat` | Instant | Fast, reliable tool calling |
| `deepseek-expert` | Expert | Stronger reasoning, less reliable tool format |

Toggle DeepThink reasoning and web search per request via `extra_body`:

```python
resp = client.chat.completions.create(
    model="deepseek-expert",
    messages=[{"role": "user", "content": "What's in the news today?"}],
    extra_body={"thinking": True, "search": True},
)
```

---

## Project layout

| Path | What it does |
|---|---|
| `deepseek/` | Core library — auth, HTTP client, PoW solver |
| `server/api.py` | FastAPI endpoints |
| `server/openai_format.py` | Prompt formatting + multi-format tool call parser |
| `server/schemas.py` | Pydantic request/response models |
| `server/config.py` | Model map, rate limit, env vars |
| `examples/` | Runnable examples |
| `AGENTS.md` | Context file for AI coding agents |
| `TOOL_CALLING_IMPROVEMENTS.md` | Full tool calling implementation notes |

---

## Notes & limitations

- **`deepseek-chat` is more reliable than `deepseek-expert` for tool calling** — the expert model sometimes narrates instead of emitting a tool call block. The parser handles 4 fallback formats but pure-prose failures are unrecoverable without a retry mechanism.
- **PoW is serialized** — all requests queue behind a lock. Don't run heavy parallel workloads.
- **Session pinning** reuses one chat thread — very long sessions may hit DeepSeek's context limit.
- **No real token counts** — `usage` is a rough `~4 chars/token` estimate.
- **Most OpenAI params ignored** — `temperature`, `top_p`, `max_tokens` are accepted but have no effect.
- **Your session is private** — `session/` is git-ignored and never leaves your machine.

---

## License

[MIT License](LICENSE). This is an unofficial project — you remain responsible for complying with DeepSeek's terms of service.

---

## Credits

Built on top of [sums001/Deepseek-API](https://github.com/sums001/Deepseek-API). Many thanks to the original author for the auth flow, PoW solver, HTTP client, and FastAPI server skeleton that make this possible.
