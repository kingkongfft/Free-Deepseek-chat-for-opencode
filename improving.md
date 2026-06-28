## Improving status

- Date: 2026-06-28
- Scope: Linux auto-run infrastructure (systemd user service + startup bash script + install helper).

### What was improved

- Created `startup.sh` — Linux bash equivalent of the existing `startup.ps1`. Sources `.env`, activates venv, starts `app.py` in background, logs to `logs/`.
- Created `deepseek-api.service` — systemd user unit for auto-start at login with auto-restart on crash.
- Created `install-service.sh` — one-shot script to link, enable, and start the systemd service; supports `--uninstall`.
- Made service tolerant of missing `.env` by using systemd's optional `-` prefix on `EnvironmentFile`.

### Why this was needed

- The project already had Windows auto-start via Task Scheduler (`startup.ps1` / `register-startup.ps1`) but no equivalent for Linux.
- Running the app manually or via tmux/screen is fragile; a systemd user service survives crashes and starts at login.

### Current code areas touched (new files)

- `startup.sh`
- `deepseek-api.service`
- `install-service.sh`

### Remaining improvement opportunities

- Add a dedicated regression test suite for spurious tool-call suppression.
- Log a compact structured reason when a tool call is suppressed.
- Consider preferring `deepseek-chat` over `deepseek-expert` for agentic continuation-heavy workloads.
