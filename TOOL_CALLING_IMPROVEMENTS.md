# DeepSeek API - Tool Calling Improvements

## Overview
Added OpenAI-compatible tool/function calling support to the DeepSeek API bridge server.
Tool calling uses prompt injection (not native API support) — tool definitions are injected
into the prompt, and the model's output is parsed for structured `<tool_call>` blocks.

---

## Changes Made

### 1. Schema Updates (`server/schemas.py`)
- Added `Tool`, `ToolChoice`, `FunctionDefinition` models
- Added `tools`, `tool_choice` fields to `ChatCompletionRequest`
- Added `tool_calls`, `tool_call_id`, `name` fields to `ChatMessage`

### 2. Tool Call Parsing (`server/openai_format.py`)
- `_example_for_tool()`: Generates a concrete few-shot example from the first tool in the request, using context-appropriate placeholder values (e.g. `filePath` → `/path/to/file.txt`, `command` → `ls -la`)
- `_format_tool_definitions()`: Injects a compact tool list + few-shot example into the system prompt. Explicit rules forbid markdown code blocks, `name=` attributes, narration, and non-`<tool_call>` XML tags
- `_parse_json_block()`: Strips markdown code fences and parses JSON from raw text
- `_make_tool_call()`: Constructs a normalized OpenAI-format tool call dict
- `_parse_invoke_block()`: Parses a single Anthropic-style `<invoke name="fn"><parameter name="k">v</parameter></invoke>` element into `(fn_name, args_dict)`
- `_summarise_completed_tool_calls()`: Scans message history and builds a checklist of already-executed tool calls (name + primary arg) to prevent the model repeating them on continuation turns
- `_parse_tool_calls()`: Parses model output for tool calls, handling all observed formats (see Tool Call Formats below)
- `messages_to_prompt()`: Smart tool injection — full definitions on new user turns, lightweight continuation prompt on tool-result turns (with completed-steps checklist)
- `completion_response()`: Returns `tool_calls` with `finish_reason: "tool_calls"` and `content: null`
- `stream_chunks()`: Buffers full output, parses tool calls, then streams in OpenAI format. Logs a `WARNING` if tools were requested but no tool call was found

### 3. API Updates (`server/api.py`)
- Passes `tools` to `messages_to_prompt()`
- Parses tool calls from non-streaming responses (passes `tools` for fallback formats)
- Passes tools to `stream_chunks()` for streaming
- Logs `DEBUG` message with incoming tool names per request
- Logs `WARNING` when tool call expected but model returned plain text
- `DEEPSEEK_SESSION_ID` support: pins requests to a single existing DeepSeek chat session
- `is_continuation` detection: avoids resuming a DeepSeek thread mid-conversation (opencode does not echo `conversation_id` back — every turn is a fresh call with the full message history)
- Dumps continuation prompt to `debug_continuation.txt` when tool results are present (for diagnosis)

### 4. Session Pinning (`server/config.py`, `server/api.py`)
By default the server calls `create_chat_session()` on every new request, creating a new chat in the DeepSeek UI each time. Setting `DEEPSEEK_SESSION_ID` pins all requests to one persistent session.

**`server/config.py`** — reads `DEEPSEEK_SESSION_ID` from env  
**`server/api.py`** — computes `effective_cid`:
```python
effective_cid = req.conversation_id or (
    DEEPSEEK_SESSION_ID if (DEEPSEEK_SESSION_ID and not is_continuation) else None
)
```
`is_continuation` is `True` when the message history contains tool results or a prior assistant turn — in that case the full context is reconstructed from `messages` directly and no DeepSeek thread resume is needed.

| `DEEPSEEK_SESSION_ID` set? | Client sends `conversation_id`? | Result |
|---|---|---|
| No | No | New chat created per request (default) |
| Yes | No | All requests go to pinned session |
| Yes | Yes | Client's `conversation_id` used (multi-turn) |

**Usage:**
```powershell
# Extract UUID from: https://chat.deepseek.com/a/chat/s/<UUID>
$env:DEEPSEEK_SESSION_ID="8431c38c-b0a6-4418-a5b2-ed35d8a14947"
python app.py
```
Or in `.env`:
```
DEEPSEEK_SESSION_ID=8431c38c-b0a6-4418-a5b2-ed35d8a14947
```

### 5. Logging (`app.py`)
- `logging.basicConfig` configured at startup with `INFO` level by default, `DEBUG` when `LOG_LEVEL=DEBUG`
- Format: `%(levelname)s %(name)s: %(message)s`

---

## opencode Tool Names
opencode sends tools with these exact API names (confirmed from binary analysis of opencode v1.17.11):

| Tool name | Required params | Optional params |
|-----------|----------------|-----------------|
| `bash` | `command: string` | `timeout: integer`, `workdir: string` |
| `read` | `filePath: string` | `offset: integer`, `limit: integer` |
| `write` | `filePath: string`, `content: string` | — |
| `edit` | `filePath: string`, `oldString: string`, `newString: string` | `replaceAll: boolean` |
| `glob` | `pattern: string` | `path: string` |
| `grep` | `pattern: string` | `path: string`, `include: string` |
| `webfetch` | `url: string` | `format: string` |
| `todowrite` | `todos: array` | — |
| `task` | `description: string`, `prompt: string`, `subagent_type: string` | `task_id: string` |

---

## Tool Call Formats
The parser handles all observed DeepSeek output variants, checked in priority order:

### Format 1 — Standard JSON (target format)
```
<tool_call>
{"name": "read", "arguments": {"filePath": "/path/to/file"}}
</tool_call>
```

### Format 2 — Named attribute (DeepSeek failure mode)
```
<tool_call name="read">{"filePath": "/path/to/file"}</tool_call>
```
Body is the arguments dict directly (no `name`/`arguments` wrapper).

### Format 3 — Anthropic XML (DeepSeek copies Claude's format)
```xml
<tool_call>
<tool_calls>
<invoke name="read">
  <parameter name="filePath" string="true">C:\path\to\file</parameter>
</invoke>
<invoke name="bash">
  <parameter name="command" string="true">git log --oneline -10</parameter>
  <parameter name="workdir" string="true">C:\project</parameter>
</invoke>
</tool_calls>
</tool_call>
```
Supports **multiple parallel tool calls** in one response. The outer `<tool_call>` wrapper is stripped before parsing `<tool_calls>`.

### Format 4 — Direct tool-name tag (last resort)
```
<write>{"filePath": "/path/to/file", "content": "..."}</write>
```
Only attempted when all above formats match nothing and tool names are known from the request.

### Format 5 — Bare fenced JSON (most common `deepseek-chat` failure mode)
````
```json
{
  "name": "write",
  "arguments": {
    "filePath": ".gitignore",
    "content": "node_modules/\n"
  }
}
```
````
Model outputs a markdown code block containing a `{"name":..,"arguments":..}` object instead of using `<tool_call>` tags. This was the root cause of the "infinite loop" bug where opencode displayed the JSON but never executed it (tool_calls was empty), and the user had to keep typing "continue".

### Format 6 — Fenced shell block (last resort, bash only)
````
```bash
npx kill-port 3000 && npm start
```
````
Model outputs a bare shell code block with no JSON at all. Matched only when tools were requested and all other formats failed. Wrapped as a `bash` tool call with `{"command": "<cmd>"}`. Only the first fenced block is taken.

### Format 7 — Split hyphenated XML tags (`deepseek-expert` failure mode)
```
<function-name>bash</function-name>
<function-params>{ "command": "npx kill-port 3000" }</function-params>
```
Model outputs the function name and parameters as separate XML tags with hyphenated names instead of a `<tool_call>` block. Observed specifically with `deepseek-expert` on continuation turns. `<function-params>` content is parsed as JSON; falls back to `{"content": raw}` if invalid.

### Stray tag cleanup
Orphaned `</tool_call>`, `<tool_call>`, `<tool_calls>` tags left over after extraction are stripped from the returned `cleaned_text`.

---

## Prompt Rules (injected per request)
```
- Do NOT wrap tool calls in ```json ... ``` markdown code blocks.
- Do NOT write any text before or after the <tool_call> block.
- Do NOT say "I'll ...", "Let me ...", or narrate your action.
- Do NOT add attributes to the tag: WRONG: <tool_call name="read"> — CORRECT: <tool_call>
- Do NOT use <write>...</write> or any XML tag other than <tool_call>.
- The JSON inside <tool_call> MUST have "name" and "arguments" keys.
- If no tool is needed, respond normally in plain text.
```

### Continuation prompt (injected when last message is a tool result)
```
System: You are a helpful assistant with access to tools: `bash`, `read`, `write`...

Already completed:
  - called `write` (index.js) ✓
  - called `write` (package.json) ✓

The tool results below have just been returned.
DO NOT repeat any tool call that is already marked completed above.
Review the results and either:
  a) Call the NEXT required tool (output ONLY a <tool_call> block, no other text), or
  b) If all steps are done, respond with a plain-text summary.
```

---

## Known Failure Modes

### 1. Markdown fenced JSON instead of `<tool_call>` (most common)
**Symptom:** Model outputs ` ```json\n{"name":"write",...}\n``` ` in content. opencode displays it but does not execute it. User must type "continue" repeatedly.  
**Fix:** Format 5 parser + explicit `Do NOT wrap in ` ```json` `` ` ` rule in prompt.

### 2. Narration instead of tool call
**Symptom:** `I'll create a markdown file with the directory listing.` — no XML tags at all.  
**Fix:** Few-shot example + "Do NOT say I'll..." prohibition. If model still emits pure prose, `finish_reason` is `stop` and the tool call is lost.

### 3. Named attribute XML
**Symptom:** `<tool_call name="read">{"filePath":"..."}` — name on the tag, no `name`/`arguments` wrapper.  
**Fix:** Format 2 parser.

### 4. Anthropic `<invoke>` XML
**Symptom:** `<tool_calls><invoke name="read"><parameter name="filePath">...</parameter></invoke></tool_calls>`  
**Fix:** Format 3 parser + `_parse_invoke_block()`.

### 5. Tool call loop on continuation turns
**Symptom:** Model repeats an already-completed tool call (e.g. writes `index.js` again after it was already written).  
**Fix:** `_summarise_completed_tool_calls()` builds an explicit checklist injected into the continuation system prompt with `DO NOT repeat` instruction.

---

## Auto-start on Windows boot (Task Scheduler)

Registered via Task Scheduler — no admin rights required. Starts at logon with a 10 s delay (gives network time to come up).

### Files
| File | Purpose |
|---|---|
| `startup.ps1` | Wrapper: kills old process on port, starts app.py hidden, writes PID to log |
| `register-startup.ps1` | Register the Task Scheduler task + immediate test run |
| `unregister-startup.ps1` | Stop the process and remove the task |
| `logs\startup.log` | Timestamp + PID written each time the task fires |
| `logs\app.log` | Uvicorn stdout (requests, INFO messages) |
| `logs\app-error.log` | Stderr / crash output |

### Install
```powershell
# Sign in first (only needed once)
python -m deepseek.auth

# Register task — also starts immediately and runs a health check
.\register-startup.ps1
```

### How it works
1. Task Scheduler fires `startup.ps1` at logon (+ 10 s delay)
2. `startup.ps1` kills any existing Python process on port 8000
3. Starts `venv\Scripts\python.exe app.py` with `-WindowStyle Hidden`
4. Logs PID to `logs\startup.log`; uvicorn output goes to `logs\app.log`

### Manage
```powershell
# Check status
Get-ScheduledTask -TaskName DeepSeekAPI | Select-Object TaskName, State

# Start manually
Start-ScheduledTask -TaskName DeepSeekAPI

# Stop
Stop-Process -Name python -ErrorAction SilentlyContinue

# Restart
Stop-Process -Name python -ErrorAction SilentlyContinue; Start-Sleep 1; Start-ScheduledTask -TaskName DeepSeekAPI
```

### Session expiry
DeepSeek sessions last ~6 hours. When expired:
```powershell
python -m deepseek.auth
Stop-Process -Name python -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskName DeepSeekAPI
```

### Remove
```powershell
.\unregister-startup.ps1
```

---

## Known Limitations
- Requires clear, specific prompts — vague prompts may not trigger tools
- `deepseek-chat` more reliable than `deepseek-expert` for tool calling; expert model tends to output fenced JSON
- Tool definitions injected via prompt injection (not native API support)
- No retry mechanism when model emits pure prose with no detectable tool call format
- Session pinning reuses one chat thread — very long sessions may hit DeepSeek context limits
- opencode does not echo `conversation_id` back — every turn is a stateless fresh call
- Auto-start task requires manual session refresh every ~6 hours (`python -m deepseek.auth` + `Start-ScheduledTask -TaskName DeepSeekAPI`)

---

## Debugging
`debug_continuation.txt` is written to the working directory on every continuation turn (when tool results are present). It contains:
1. The full `messages` array as received from opencode
2. The exact prompt string sent to DeepSeek

```powershell
# Tail the file after triggering a continuation turn
Get-Content debug_continuation.txt
```

---

## Testing
```bash
# Test non-streaming tool call (write tool)
curl -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-chat",
    "messages": [{"role": "user", "content": "save hello world to /tmp/test.txt"}],
    "tools": [{"type": "function", "function": {"name": "write", "description": "Writes a file.", "parameters": {"type": "object", "properties": {"filePath": {"type": "string"}, "content": {"type": "string"}}, "required": ["filePath", "content"]}}}]
  }'

# Test continuation turn (simulate tool result)
curl -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-chat",
    "messages": [
      {"role": "user", "content": "create index.js and package.json"},
      {"role": "assistant", "content": null, "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "write", "arguments": "{\"filePath\":\"index.js\",\"content\":\"console.log(1)\"}"}}]},
      {"role": "tool", "tool_call_id": "call_1", "name": "write", "content": "Wrote file successfully."}
    ],
    "tools": [{"type": "function", "function": {"name": "write", "description": "Writes a file.", "parameters": {"type": "object", "properties": {"filePath": {"type": "string"}, "content": {"type": "string"}}, "required": ["filePath", "content"]}}}]
  }'

# Enable debug logging
LOG_LEVEL=DEBUG python app.py
```
