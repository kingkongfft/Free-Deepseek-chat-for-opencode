# Hermes setup: free DeepSeek LLM provider

Wire hermes to use DeepSeek's free web chat via the local API server — no API keys, no credits.

## 1. Start the server

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python -m deepseek.auth    # sign in once — browser opens
python app.py              # http://127.0.0.1:8000
```

Verify:
```bash
curl http://127.0.0.1:8000/healthz
# {"status":"ok"}
```

## 2. Auto-start (optional)

```bash
./install-service.sh       # systemd user service — starts on login
journalctl --user -u deepseek-api.service -f  # watch logs
```

## 3. Configure hermes

The `local-free-openseek` provider is already added to `~/.hermes/config.yaml`:

```yaml
model:
  default: deepseek-chat
  provider: local-free-openseek

providers:
  local-free-openseek:
    base_url: http://127.0.0.1:8000/v1
    default_model: deepseek-chat
    context_length: 1000000
    max_tokens: 8192
    api_mode: chat_completions
```

No API key needed — the local server accepts all requests.

## 4. Verify

```bash
hermes doctor      # check connectivity
hermes "hello"     # test a chat
```

## Models

| Model | Use case |
|---|---|
| `deepseek-chat` | Default. Fast, reliable tool calling. **Use for all agentic tasks.** |
| `deepseek-expert` | Stronger reasoning, but unreliable for tool calling — use for one-shot questions only. |

Pass `thinking` / `search` via `extra_body` for DeepThink reasoning or web search.

## Session expiry

DeepSeek sessions last ~6 hours. Refresh when needed:

```bash
python -m deepseek.auth              # re-auth
systemctl --user restart deepseek-api.service  # restart service
```
