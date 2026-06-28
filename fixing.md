## Fixing status

- Date: 2026-06-28
- Issue: continuation turns could loop on `bash` when the user asked to print README/file content.

### Observed failure mode

- The server correctly handled the initial `read` tool call.
- On the continuation turn, the model emitted bad `bash` tool calls such as:
  - `markdown\n# local-test ...`
  - raw markdown/prose content beginning with `#`
  - `md\n# local-test ...`
  - `Get-Content -Path README.md`
- These commands were attempts to display text, not legitimate shell actions.

### What was done

- Investigated `debug_continuation.txt`, `debug_request.json`, `server/openai_format.py`, and `server/api.py`.
- Confirmed the original repetition guard alone was insufficient because the model varied the bad command text.
- Added stronger suppression logic in `server/openai_format.py` to convert suspicious display-style `bash` tool calls into plain text responses.
- Applied suppression in both non-stream and stream execution paths in `server/api.py`.
- Committed and pushed the source changes.

### Git status

- Commit pushed: `0617e14` — `Harden tool-call loop handling`

### Verification status

- Partial verification completed:
  - repeated markdown/prose display-style `bash` calls are identified by the new suppression logic.
  - loop-detection replay against captured request history still triggers.
- Follow-up verification still recommended on a live reproduced request to confirm all variants, especially file-display shell commands, are fully suppressed end-to-end.

### Files involved

- `server/openai_format.py`
- `server/api.py`
- `debug_continuation.txt`
- `debug_request.json`
