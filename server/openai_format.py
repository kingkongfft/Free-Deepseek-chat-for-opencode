"""Translate between OpenAI's chat-completions shapes and our DeepSeek client.

DeepSeek's protocol has no system/role channel — just a single `prompt` string.
So we flatten the OpenAI `messages` array into one prompt, and wrap DeepSeek's
text output back into OpenAI response/stream objects.

When tools are provided, we inject tool definitions into the prompt and parse
the model's output for structured tool calls.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .schemas import ChatMessage, Tool

_ROLE_LABELS = {"system": "System", "user": "User", "assistant": "Assistant"}
_log = logging.getLogger(__name__)


def _text_of(content) -> str:
    """Extract plain text from a message's content (string or list-of-parts).

    Handles OpenAI content-part arrays, including:
      - {"type": "text", "text": "..."}           — plain text
      - {"type": "file", "file": {...}}            — opencode @file mention (OpenAI files API shape)
      - {"type": "document", ...}                 — Anthropic-style document block
      - {"type": "image_url", ...}                — images (described, not passed as pixels)
    Unknown types are logged at DEBUG level so they can be diagnosed.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for p in content:
        if not isinstance(p, dict):
            continue
        t = p.get("type")
        if t == "text":
            parts.append(p.get("text", ""))
        elif t == "file":
            # OpenAI files API shape used by opencode @file mentions:
            # {"type": "file", "file": {"filename": "...", "content": "..."}}
            file_obj = p.get("file") or {}
            filename = file_obj.get("filename") or file_obj.get("name") or "file"
            file_text = (
                file_obj.get("content")  # text/base64 content
                or file_obj.get("text")
                or p.get("content")  # fallback: content at top level
                or p.get("text")
                or ""
            )
            if file_text:
                parts.append(f"[File: {filename}]\n{file_text}")
            else:
                _log.debug("_text_of: file part has no readable content: %s", p)
        elif t == "document":
            # Anthropic-style: {"type": "document", "source": {"type": "text", "data": "..."}}
            source = p.get("source") or {}
            doc_text = source.get("data") or source.get("text") or p.get("text") or ""
            title = p.get("title") or source.get("filename") or "document"
            if doc_text:
                parts.append(f"[Document: {title}]\n{doc_text}")
        elif t == "image_url":
            url = (p.get("image_url") or {}).get("url", "")
            if url.startswith("data:"):
                parts.append("[Image: embedded base64 image — not shown]")
            else:
                parts.append(f"[Image: {url}]")
        else:
            _log.debug("_text_of: unhandled content part type %r: %s", t, p)
    return "\n".join(parts)


def _example_for_tool(tools: List[Tool]) -> str:
    """Generate a concrete few-shot example using the first available tool."""
    if not tools:
        return ""
    fn = tools[0].function
    name = fn.name
    params = fn.parameters or {}
    props = params.get("properties", {})
    required = params.get("required", [])

    # Build minimal example args from required params
    example_args: Dict[str, Any] = {}
    for k in required[:2]:  # max 2 args for brevity
        prop = props.get(k, {})
        typ = prop.get("type", "string")
        if typ == "string":
            # Use context-appropriate placeholders
            if "path" in k.lower() or "file" in k.lower():
                example_args[k] = "/path/to/file.txt"
            elif "content" in k.lower():
                example_args[k] = "file content here"
            elif "command" in k.lower():
                example_args[k] = "ls -la"
            elif "pattern" in k.lower():
                example_args[k] = "*.py"
            elif "url" in k.lower():
                example_args[k] = "https://example.com"
            elif "old" in k.lower():
                example_args[k] = "old text"
            elif "new" in k.lower():
                example_args[k] = "new text"
            else:
                example_args[k] = f"<{k}>"
        elif typ in ("integer", "number"):
            example_args[k] = 0
        elif typ == "boolean":
            example_args[k] = False
        elif typ == "array":
            example_args[k] = []

    return f"""EXAMPLE — if you need to call `{name}`:
<tool_call>
{json.dumps({"name": name, "arguments": example_args}, indent=2)}
</tool_call>"""


def _format_tool_definitions(tools: List[Tool]) -> str:
    """Format tool definitions into a system prompt section."""
    tool_list = []
    for tool in tools:
        fn = tool.function
        # Show just the parameter names and types, not the full JSON schema (too long)
        params = fn.parameters or {}
        props = params.get("properties", {})
        required = set(params.get("required", []))
        param_strs = []
        for pname, pdef in props.items():
            ptype = pdef.get("type", "any")
            req_marker = "" if pname in required else "?"
            param_strs.append(f"{pname}{req_marker}: {ptype}")
        params_summary = ", ".join(param_strs) if param_strs else "no params"
        desc = (fn.description or "No description").split("\n")[0][:120]
        tool_list.append(f"- {fn.name}({params_summary}) — {desc}")

    tools_text = "\n".join(tool_list)
    example = _example_for_tool(tools)

    return f"""[TOOL USE INSTRUCTIONS — FOLLOW EXACTLY]
You have access to these tools:
{tools_text}

OUTPUT FORMAT — when using a tool your ENTIRE response must be ONLY this:
<tool_call>
{{"name": "TOOL_NAME", "arguments": {{"PARAM": "VALUE", ...}}}}
</tool_call>

{example}

MANDATORY RULES:
- Do NOT wrap tool calls in ```json ... ``` markdown code blocks.
- Do NOT write any text before or after the <tool_call> block.
- Do NOT say "I'll ...", "Let me ...", or narrate your action.
- Do NOT add attributes to the tag: WRONG: <tool_call name="read"> — CORRECT: <tool_call>
- Do NOT use <write>...</write> or any XML tag other than <tool_call>.
- The JSON inside <tool_call> MUST have "name" and "arguments" keys.
- If no tool is needed, respond normally in plain text.
[END TOOL USE INSTRUCTIONS]"""


def _parse_json_block(raw: str) -> Optional[Dict[str, Any]]:
    """Try to parse a JSON object from raw text, stripping code fences."""
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _make_tool_call(name: str, arguments: Any) -> Dict[str, Any]:
    return {
        "id": "call_" + uuid.uuid4().hex[:16],
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments)
            if not isinstance(arguments, str)
            else arguments,
        },
    }


def _parse_invoke_block(invoke_text: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Parse an Anthropic-style <invoke name="fn"><parameter name="k">v</parameter>...</invoke> block.

    Returns (fn_name, args_dict) or None if parsing fails.
    """
    name_m = re.search(r'<invoke\s+name=["\']([^"\']+)["\']', invoke_text)
    if not name_m:
        return None
    fn_name = name_m.group(1)
    # Extract all <parameter name="k">v</parameter> pairs
    params = re.findall(
        r'<parameter\s+name=["\']([^"\']+)["\'][^>]*>\s*(.*?)\s*</parameter>',
        invoke_text,
        re.DOTALL,
    )
    args: Dict[str, Any] = {}
    for k, v in params:
        # Try to parse value as JSON (handles booleans, numbers, objects, arrays)
        obj = _parse_json_block(v)
        args[k] = obj if obj is not None else v.strip()
    return fn_name, args


def _parse_tool_calls(
    text: str,
    tools: Optional[List[Tool]] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    """Parse tool calls from model output.

    Returns (cleaned_text, tool_calls) where cleaned_text has the
    tool call blocks removed.

    Handles all observed DeepSeek output formats:
    1. Standard:      <tool_call>{"name": "fn", "arguments": {...}}</tool_call>
    2. Named attr:    <tool_call name="fn">{"arg": "val"}</tool_call>
    3. Anthropic XML: <tool_calls><invoke name="fn"><parameter name="k">v</parameter></invoke></tool_calls>
    4. Direct tag:    <fn_name>{"arg": "val"}</fn_name>
    5. Code-fenced JSON inside any of the above
    6. Fenced shell block: ```bash\n<cmd>\n```
    7. Split hyphenated tags: <function-name>fn</function-name><function-params>{...}</function-params>
    8. Narration text before/after any block (stripped from content)
    9. Stray/orphaned closing tags are stripped
    """
    tool_calls: List[Dict[str, Any]] = []
    cleaned = text

    # --- Format 3 (highest priority): Anthropic <tool_calls><invoke>...</invoke></tool_calls> ---
    # Also handles a bare outer <tool_call> wrapping the <tool_calls> block.
    # Strip outer <tool_call>...</tool_call> wrapper if it encloses a <tool_calls> block.
    outer_wrap = re.search(
        r"<tool_call>\s*(<tool_calls>.*?</tool_calls>)\s*</tool_call>", text, re.DOTALL
    )
    if outer_wrap:
        # Unwrap: treat the inner <tool_calls> block as the canonical text for this format
        text_for_anthropic = outer_wrap.group(1)
        cleaned = re.sub(
            r"<tool_call>\s*<tool_calls>.*?</tool_calls>\s*</tool_call>",
            "",
            cleaned,
            flags=re.DOTALL,
        ).strip()
    else:
        text_for_anthropic = text

    tc_blocks_pattern = r"<tool_calls>\s*(.*?)\s*</tool_calls>"
    tc_blocks = re.findall(tc_blocks_pattern, text_for_anthropic, re.DOTALL)
    if tc_blocks:
        for block in tc_blocks:
            # Each block may contain multiple <invoke> elements
            invoke_pattern = r"<invoke(?:\s[^>]*)?>.*?</invoke>"
            invokes = re.findall(invoke_pattern, block, re.DOTALL)
            for inv in invokes:
                result = _parse_invoke_block(inv)
                if result:
                    fn_name, args = result
                    tool_calls.append(_make_tool_call(fn_name, args))
        cleaned = re.sub(tc_blocks_pattern, "", cleaned, flags=re.DOTALL).strip()

    # --- Format 1: <tool_call>{"name": "fn", "arguments": {...}}</tool_call> ---
    if not tool_calls:
        tc_pattern = r"<tool_call>\s*(.*?)\s*</tool_call>"
        tc_matches = re.findall(tc_pattern, text, re.DOTALL)
        if tc_matches:
            for raw in tc_matches:
                obj = _parse_json_block(raw)
                if obj and "name" in obj:
                    tool_calls.append(
                        _make_tool_call(obj["name"], obj.get("arguments", {}))
                    )
                else:
                    name_m = re.search(r'"name"\s*:\s*"([^"]+)"', raw)
                    args_m = re.search(r'"arguments"\s*:\s*(\{.*?\})', raw, re.DOTALL)
                    if name_m:
                        tool_calls.append(
                            _make_tool_call(
                                name_m.group(1),
                                args_m.group(1) if args_m else "{}",
                            )
                        )
            cleaned = re.sub(tc_pattern, "", cleaned, flags=re.DOTALL).strip()

    # --- Format 2: <tool_call name="fn">{args}</tool_call> ---
    if not tool_calls:
        named_pattern = r'<tool_call\s+name=["\']([^"\']+)["\']>\s*(.*?)\s*</tool_call>'
        named_matches = re.findall(named_pattern, text, re.DOTALL)
        if named_matches:
            for fn_name, raw in named_matches:
                obj = _parse_json_block(raw)
                if obj is not None:
                    tool_calls.append(_make_tool_call(fn_name, obj))
                else:
                    tool_calls.append(
                        _make_tool_call(fn_name, {"content": raw.strip()})
                    )
            cleaned = re.sub(named_pattern, "", cleaned, flags=re.DOTALL).strip()

    # Strip any stray/orphaned XML tags left over
    cleaned = re.sub(r"</tool_call>", "", cleaned).strip()
    cleaned = re.sub(r"<tool_calls?>", "", cleaned).strip()

    # --- Format 4: <tool_name>...</tool_name> using actual tool names ---
    # Only attempted when all above found nothing, and we know the tool names.
    if not tool_calls and tools:
        known_names = [t.function.name for t in tools]
        for name in known_names:
            tag_pattern = rf"<{re.escape(name)}>\s*(.*?)\s*</{re.escape(name)}>"
            tag_matches = re.findall(tag_pattern, text, re.DOTALL)
            for raw in tag_matches:
                obj = _parse_json_block(raw)
                if obj is not None:
                    tool_calls.append(_make_tool_call(name, obj))
                else:
                    tool_calls.append(_make_tool_call(name, {"content": raw.strip()}))
            if tag_matches:
                cleaned = re.sub(tag_pattern, "", cleaned, flags=re.DOTALL).strip()

    # --- Format 5: bare fenced JSON ```json\n{"name":..,"arguments":..}\n``` ---
    # Model outputs a markdown code block containing a tool call JSON object.
    # This happens when the model ignores XML tag instructions entirely.
    if not tool_calls:
        fence_pattern = r"```(?:json)?\s*(\{.*?\})\s*```"
        fence_matches = re.findall(fence_pattern, text, re.DOTALL)
        for raw in fence_matches:
            obj = _parse_json_block(raw)
            if obj and "name" in obj and "arguments" in obj:
                tool_calls.append(_make_tool_call(obj["name"], obj["arguments"]))
        if tool_calls:
            cleaned = re.sub(fence_pattern, "", cleaned, flags=re.DOTALL).strip()

    # --- Format 7: <function-name>fn</function-name><function-params>{...}</function-params> ---
    # Model outputs split XML tags with hyphenated names.
    # e.g. <function-name>bash</function-name>\n<function-params>{"command": "ls"}</function-params>
    if not tool_calls:
        fn_name_pattern = r"<function-name>\s*(.*?)\s*</function-name>"
        fn_params_pattern = r"<function-params>\s*(.*?)\s*</function-params>"
        fn_name_m = re.search(fn_name_pattern, text, re.DOTALL)
        fn_params_m = re.search(fn_params_pattern, text, re.DOTALL)
        if fn_name_m:
            fn_name = fn_name_m.group(1).strip()
            raw_params = fn_params_m.group(1).strip() if fn_params_m else "{}"
            obj = _parse_json_block(raw_params)
            args = obj if obj is not None else {"content": raw_params}
            tool_calls.append(_make_tool_call(fn_name, args))
            cleaned = re.sub(fn_name_pattern, "", cleaned, flags=re.DOTALL)
            cleaned = re.sub(fn_params_pattern, "", cleaned, flags=re.DOTALL).strip()

    # --- Format 6: fenced shell blocks as bash tool call (last resort) ---
    # Model outputs ```bash\n<cmd>\n``` instead of <tool_call>. Only attempts
    # when tools were explicitly requested and no other format matched.
    if not tool_calls and tools:
        # Match the FIRST fenced code block (bash/sh/cmd/powershell or no lang)
        # Skip blocks whose content is clearly not a shell command (JSON-like, etc.)
        fence_pattern = r"```(?:bash|shell|sh|cmd|powershell|pwsh)?\s*\n?(.*?)\n?```"
        fence_matches = re.findall(fence_pattern, text, re.DOTALL)
        for raw in fence_matches:
            cmd = raw.strip()
            # Skip JSON-like blocks (handled by Format 5 above) and multi-line
            # code snippets that look like file content, not a command.
            if not cmd:
                continue
            if cmd.startswith("{") or cmd.startswith("["):
                continue
            tool_calls.append(_make_tool_call("bash", {"command": cmd}))
            break  # only take the first fenced command block
        if tool_calls:
            cleaned = re.sub(fence_pattern, "", cleaned, flags=re.DOTALL).strip()

    return cleaned, tool_calls


def _summarise_completed_tool_calls(messages: List[ChatMessage]) -> str:
    """Build a compact summary of tool calls already executed in this conversation,
    so the model knows not to repeat them."""
    done = []
    for m in messages:
        if m.role == "assistant" and m.tool_calls:
            for tc in m.tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "?")
                try:
                    args = json.loads(fn.get("arguments", "{}"))
                except Exception:
                    args = {}
                # Show a one-line summary per call
                key_arg = (
                    args.get("filePath")
                    or args.get("command")
                    or args.get("url")
                    or args.get("pattern")
                    or args.get("query")
                    or ""
                )
                hint = f"({key_arg})" if key_arg else ""
                done.append(f"  - called `{name}` {hint} ✓")
    return "\n".join(done)


def messages_to_prompt(
    messages: List[ChatMessage],
    tools: Optional[List[Tool]] = None,
) -> Tuple[str, bool]:
    """Flatten a chat history into a single prompt DeepSeek can answer.

    Returns (prompt, has_tools) where has_tools indicates if tools were injected.

    On continuation turns (last message is a tool result):
    - Builds a clear summary of what was already done
    - Shows each tool result explicitly
    - Tells the model to continue WITHOUT repeating completed steps
    """
    has_tools = False

    # Fast path: single user message
    if len(messages) == 1 and messages[0].role == "user":
        text = _text_of(messages[0].content)
        if tools:
            tool_section = _format_tool_definitions(tools)
            text = f"{tool_section}\n\nUser: {text}"
            has_tools = True
        return text, has_tools

    # Detect continuation: ends with one or more tool result messages
    last_role = next(
        (m.role for m in reversed(messages) if m.role != "system"),
        "user",
    )
    ends_with_tool_result = last_role == "tool"

    lines = []

    # On continuation turns, emit original system messages BEFORE our
    # continuation prompt. Otherwise the massive opencode system prompt
    # (500+ lines) comes after our "output ONLY a <tool_call>" instruction
    # and contradicts it, causing the model to narrate instead of tool-calling.
    if ends_with_tool_result and tools:
        for m in messages:
            if m.role == "system":
                sys_text = _text_of(m.content)
                if sys_text:
                    lines.append(f"System: {sys_text}")

    if tools:
        has_tools = True
        if ends_with_tool_result:
            # Show only the last 10 completed steps to keep prompt compact
            completed = _summarise_completed_tool_calls(messages)
            completed_lines = completed.split("\n")
            if len(completed_lines) > 10:
                completed_lines = completed_lines[-10:]
                completed_lines.insert(
                    0,
                    f"  ... ({len(completed.split(chr(10))) - 10} earlier steps omitted)",
                )
            completed = "\n".join(completed_lines)
            completed_block = f"\nAlready completed:\n{completed}" if completed else ""
            # Compact long tool lists (opencode sends 60+ tools)
            if len(tools) > 10:
                common = [
                    t.function.name
                    for t in tools
                    if t.function.name
                    in {
                        "bash",
                        "read",
                        "write",
                        "edit",
                        "glob",
                        "grep",
                        "webfetch",
                        "todowrite",
                        "task",
                        "skill",
                    }
                ]
                remaining = len(tools) - len(common)
                tool_names = ", ".join(f"`{n}`" for n in common)
                if remaining > 0:
                    tool_names += f" (and {remaining} more)"
            else:
                tool_names = ", ".join(f"`{t.function.name}`" for t in tools)
            lines.append(
                f"System: You are a helpful assistant with access to tools: {tool_names}.\n"
                f"{completed_block}\n"
                f"The tool results below have just been returned. "
                f"DO NOT repeat any tool call that is already marked completed above. "
                f"Review the results and either:\n"
                f"  a) Call the NEXT required tool (output ONLY a <tool_call> block, no other text), or\n"
                f"  b) If all steps are done, respond with a plain-text summary.\n"
                f"Tool call format reminder:\n"
                f"<tool_call>\n"
                f'{{"name": "TOOL_NAME", "arguments": {{"PARAM": "VALUE"}}}}\n'
                f"</tool_call>"
            )
        else:
            tool_section = _format_tool_definitions(tools)
            lines.append(f"System: {tool_section}")

    for m in messages:
        if m.role == "system":
            if ends_with_tool_result and tools:
                continue  # already emitted above (before continuation prompt)
            sys_text = _text_of(m.content)
            if sys_text:
                lines.append(f"System: {sys_text}")
        elif m.role == "tool":
            content = _text_of(m.content) if m.content else "(no output)"
            tool_name = m.name or ""
            name_hint = f" ({tool_name})" if tool_name else ""
            lines.append(f"ToolResult{name_hint}: {content}")
        elif m.role == "assistant" and m.tool_calls:
            for tc in m.tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "unknown")
                args = fn.get("arguments", "{}")
                lines.append(
                    f"Assistant: <tool_call>\n"
                    f'{{"name": "{name}", "arguments": {args}}}\n'
                    f"</tool_call>"
                )
            if m.content:
                lines.append(f"Assistant: {_text_of(m.content)}")
        else:
            label = _ROLE_LABELS.get(m.role, m.role.capitalize())
            text = _text_of(m.content)
            if text:
                lines.append(f"{label}: {text}")

    lines.append("Assistant:")
    return "\n\n".join(lines), has_tools


def _now() -> int:
    return int(time.time())


def _id() -> str:
    return "chatcmpl-" + uuid.uuid4().hex


def _est_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token) — DeepSeek's web API gives us no count."""
    return max(1, len(text) // 4)


def completion_response(
    model: str,
    content: str,
    prompt: str,
    conversation_id: str = None,
    tool_calls: Optional[List[Dict[str, Any]]] = None,
) -> dict:
    """A full (non-streaming) OpenAI chat.completion object.

    `conversation_id` is an extra top-level field (outside OpenAI's schema) you
    send back to resume the conversation.
    """
    pt, ct = _est_tokens(prompt), _est_tokens(content)

    message: Dict[str, Any] = {"role": "assistant"}
    if tool_calls:
        message["content"] = None
        message["tool_calls"] = tool_calls
    else:
        message["content"] = content or None

    finish = "tool_calls" if tool_calls else "stop"

    return {
        "id": _id(),
        "object": "chat.completion",
        "created": _now(),
        "model": model,
        "conversation_id": conversation_id,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish,
            }
        ],
        "usage": {
            "prompt_tokens": pt,
            "completion_tokens": ct,
            "total_tokens": pt + ct,
        },
    }


def stream_chunks(
    model: str,
    stream: Iterable[str],
    tools: Optional[List[Tool]] = None,
) -> Iterable[str]:
    """Yield OpenAI SSE lines (`data: {...}\\n\\n`) for a streamed completion.

    `stream` is the client's stream object; after it's consumed we read its
    `.conversation_id` and attach it to the final chunk.

    When tools are provided, we buffer the output and parse for tool calls
    at the end.
    """
    cid, created = _id(), _now()

    def frame(delta: dict, finish=None, conversation_id: str = None) -> str:
        obj = {
            "id": cid,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        if conversation_id is not None:
            obj["conversation_id"] = conversation_id
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

    if tools:
        # Buffer all output and parse for tool calls at the end
        buffer = []
        for d in stream:
            if d:
                buffer.append(d)

        full_text = "".join(buffer)
        cleaned_text, tool_calls = _parse_tool_calls(full_text, tools=tools)

        if tool_calls:
            # Yield role chunk
            yield frame({"role": "assistant", "content": None})

            # Yield each tool call in OpenAI streaming format
            for tc in tool_calls:
                fn = tc["function"]
                # First chunk: tool call id and function name
                yield frame(
                    {
                        "content": None,
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": tc["id"],
                                "type": "function",
                                "function": {"name": fn["name"], "arguments": ""},
                            }
                        ],
                    }
                )
                # Second chunk: arguments
                yield frame(
                    {
                        "content": None,
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"arguments": fn["arguments"]},
                            }
                        ],
                    }
                )

            conversation_id = getattr(stream, "conversation_id", None)
            yield frame({}, finish="tool_calls", conversation_id=conversation_id)
        else:
            # No tool calls found — model ignored tool instructions and responded in plain text.
            # This is a known failure mode, especially with deepseek-expert.
            _log.warning(
                "Tool call expected but model returned plain text. "
                "Model may have narrated instead of using <tool_call> tags. "
                "Response: %.200s",
                cleaned_text,
            )
            yield frame({"role": "assistant", "content": ""})
            if cleaned_text:
                yield frame({"content": cleaned_text})
            conversation_id = getattr(stream, "conversation_id", None)
            yield frame({}, finish="stop", conversation_id=conversation_id)
    else:
        # Original streaming behavior - no tools
        yield frame({"role": "assistant", "content": ""})
        for d in stream:
            if d:
                yield frame({"content": d})
        conversation_id = getattr(stream, "conversation_id", None)
        yield frame({}, finish="stop", conversation_id=conversation_id)

    yield "data: [DONE]\n\n"
