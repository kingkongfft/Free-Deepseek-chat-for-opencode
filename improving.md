## Improving status

- Date: 2026-06-28
- Scope: harden tool-call continuation handling for opencode-style clients using the DeepSeek-compatible server.

### What was improved

- Expanded loop detection in `server/openai_format.py` so repeated trailing tool calls can disable tool injection and force a plain-text answer.
- Added suppression for bogus `bash` tool calls that are clearly trying to display text instead of execute a real shell command.
- Wired suppression into both non-stream and stream paths in `server/api.py`.
- Preserved the existing continuation prompt improvements and layered the new safeguards on top.

### Why this was needed

- The model was reading a file correctly, then trying to "print" the file by calling `bash` with markdown or prose as the shell command.
- The model changed the bogus command shape across retries, so a simple exact-repeat guard was not enough.

### Current code areas touched

- `server/openai_format.py`
- `server/api.py`

### Remaining improvement opportunities

- Add a dedicated regression test suite for spurious tool-call suppression.
- Log a compact structured reason when a tool call is suppressed.
- Consider preferring `deepseek-chat` over `deepseek-expert` for agentic continuation-heavy workloads.
