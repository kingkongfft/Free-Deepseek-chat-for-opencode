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
- `_format_tool_definitions()`: Injects a compact tool list + few-shot example into the system prompt. Shows params as `name(param: type, optional?: type) — description` to reduce prompt bloat. Explicit rules forbid `name=` attributes and narration.
- `_parse_json_block()`: Strips markdown code fences and parses JSON from raw text
- `_make_tool_call()`: Constructs a normalized OpenAI-format tool call dict
- `_parse_invoke_block()`: Parses a single Anthropic-style `<invoke name="fn"><parameter name="k">v</parameter></invoke>` element into `(fn_name, args_dict)`
- `_parse_tool_calls()`: Parses model output for tool calls, handling all observed formats (see Tool Call Formats below)
- `messages_to_prompt()`: Handles tool messages and tool call messages in conversation history
- `completion_response()`: Returns `tool_calls` with `finish_reason: "tool_calls"` and `content: null`
- `stream_chunks()`: Buffers full output, parses tool calls, then streams in OpenAI format. Logs a `WARNING` if tools were requested but no tool call was found (model narrated instead)

### 3. API Updates (`server/api.py`)
- Passes `tools` to `messages_to_prompt()`
- Parses tool calls from non-streaming responses (passes `tools` for Format 2 fallback)
- Passes tools to `stream_chunks()` for streaming
- Logs `DEBUG` message with incoming tool names per request
- Logs `WARNING` when tool call expected but model returned plain text
- `DEEPSEEK_SESSION_ID` support: all requests are pinned to a single existing DeepSeek chat session instead of creating a new one per request (see Session Pinning below)

### 4. Session Pinning (`server/config.py`, `server/api.py`)
By default the server calls `create_chat_session()` on every new request, creating a new chat in the DeepSeek UI each time. Setting `DEEPSEEK_SESSION_ID` pins all requests to one persistent session.

**`server/config.py`** — reads `DEEPSEEK_SESSION_ID` from env  
**`server/api.py`** — computes `effective_cid`:
```python
effective_cid = req.conversation_id or (DEEPSEEK_SESSION_ID if DEEPSEEK_SESSION_ID else None)
```
The client's own `conversation_id` (from a prior response) always takes priority so multi-turn threading continues to work correctly.

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
Supports **multiple parallel tool calls** in one response. Parameter values are JSON-parsed where possible (handles booleans, numbers, objects, arrays). The outer `<tool_call>` wrapper is stripped before parsing `<tool_calls>`.

### Format 4 — Direct tool-name tag (last resort)
```
<write>{"filePath": "/path/to/file", "content": "..."}</write>
```
Only attempted when all above formats match nothing and tool names are known from the request.

### Stray tag cleanup
Orphaned `</tool_call>`, `<tool_call>`, `<tool_calls>` tags left over after extraction are stripped from the returned `cleaned_text`.

---

## Prompt Rules (injected per request)
```
- Do NOT write any text before or after the <tool_call> block.
- Do NOT say "I'll ...", "Let me ...", or narrate your action.
- Do NOT add attributes to the tag: WRONG: <tool_call name="read"> — CORRECT: <tool_call>
- Do NOT use <write>...</write> or any XML tag other than <tool_call>.
- The JSON inside <tool_call> MUST have "name" and "arguments" keys.
- If no tool is needed, respond normally in plain text.
```

---

## Response Format
When tool calls are present:
```json
{
  "choices": [{
    "message": {
      "role": "assistant",
      "content": null,
      "tool_calls": [{
        "id": "call_xxx",
        "type": "function",
        "function": {
          "name": "bash",
          "arguments": "{\"command\": \"ls\"}"
        }
      }]
    },
    "finish_reason": "tool_calls"
  }]
}
```

---

## Streaming Format
Tool calls are streamed in OpenAI format:
1. Role chunk: `{"role": "assistant", "content": null}`
2. Tool call chunk with id and name
3. Tool call chunk with arguments
4. Final chunk with `finish_reason: "tool_calls"`

---

## Known Failure Mode: Model Narrates Instead of Calling Tool
**Symptom:** Model responds with `I'll create a markdown file with the directory listing.` instead of emitting a `<tool_call>` block.

**Root cause:** DeepSeek (especially `deepseek-expert`) ignores tool call format instructions and narrates its intent instead. This is a prompt injection limitation — there is no native tool calling API.

**Mitigations applied:**
1. **Few-shot example** — `_example_for_tool()` injects a concrete filled-in example of the first tool, making the expected format unambiguous
2. **Explicit prohibition** — prompt forbids `"I'll ..."`, `"Let me ..."`, `name=` attributes, and non-`<tool_call>` XML tags
3. **Multi-format fallback parser** — `_parse_tool_calls()` handles 4 different output formats including Anthropic XML with parallel invocations
4. **Warning log** — server logs `WARNING` with the first 200 chars of the bad response for diagnosis

**Remaining limitation:** If the model emits pure prose with no XML tags at all, the tool call is lost and `finish_reason` will be `stop`. The client (opencode) will then treat it as a plain assistant reply and not execute the tool.

---

## Known Limitations
- Requires clear, specific prompts for tool calls (vague prompts may not trigger tools)
- `deepseek-chat` model responds more reliably to tool calls than `deepseek-expert`
- Tool definitions are injected via prompt injection (not native API support)
- No retry mechanism when model fails to emit a tool call
- Session pinning reuses a single chat thread — very long sessions may hit DeepSeek context limits

---

## Testing
```bash
# Test non-streaming tool call (write tool — the common failure case)
curl -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-chat",
    "messages": [{"role": "user", "content": "save hello world to /tmp/test.txt"}],
    "tools": [{"type": "function", "function": {"name": "write", "description": "Writes a file to the local filesystem.", "parameters": {"type": "object", "properties": {"filePath": {"type": "string"}, "content": {"type": "string"}}, "required": ["filePath", "content"]}}}]
  }'

# Test non-streaming bash tool call
curl -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-chat",
    "messages": [{"role": "user", "content": "list files"}],
    "tools": [{"type": "function", "function": {"name": "bash", "description": "Execute bash command", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}}]
  }'

# Enable debug logging to see incoming tool names
LOG_LEVEL=DEBUG python app.py
```
