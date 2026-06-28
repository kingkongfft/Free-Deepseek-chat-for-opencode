# opencode setup: free DeepSeek LLM provider

Configure opencode to use the free DeepSeek API server running locally.

## 1. Start the server

```bash
python app.py              # http://127.0.0.1:8000
```

Or use the systemd service for auto-start:
```bash
./install-service.sh
```

## 2. Add the provider

Edit `~/.config/opencode/opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "defaultProvider": "local-free-deepseek",
  "provider": {
    "local-free-deepseek": {
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

## 3. Select the model

Launch opencode, press `Ctrl+P` → **Model** → choose **DeepSeek Chat (Local)**.

Use `deepseek-chat` for all agentic/tool-calling tasks — it has reliable tool calling.  
Use `deepseek-expert` only for one-shot reasoning questions (no tool use).

## Models

| Model | opencode name | Use case |
|---|---|---|
| `deepseek-chat` | DeepSeek Chat (Local) | Fast, reliable tool calling. Default for all tasks. |
| `deepseek-expert` | DeepSeek Expert (Local) | Stronger reasoning, unreliable tool format. |
