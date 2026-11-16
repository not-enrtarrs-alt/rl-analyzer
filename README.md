# rl-analyzer

A Python 3.11+ Windows CLI that selects the latest eligible uploaded 3v3 replay for a fixed trio, extracts stats, asks an AI for one funny recap, and saves it for manual posting by default. SQLite deduplicates matches using available match identifiers. No live X posts were made during development.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m rl_analyzer doctor --offline
.venv\Scripts\python -m rl_analyzer demo
```

The offline demo writes `out/demo_tweet.txt`; it uses no network or database. It may copy to the clipboard unless `CLIPBOARD_ENABLED=false` is set in the environment.

## First run

1. If `.env` does not already exist, copy `.env.example` to `.env` (`if (-not (Test-Path .env)) { Copy-Item .env.example .env }`). Never overwrite an existing configuration or share the file.
2. Set `BALLCHASING_TOKEN`, three profile URLs/IDs and aliases. Replays must already be uploaded and visible. See [ballchasing setup](docs/SETUP_BALLCHASING.md).
3. Install Ollama and run `ollama pull llama3.1:8b`, then `ollama serve` if it is not already running, or configure a hosted provider. See [AI setup](docs/SETUP_AI.md).
4. Run `.venv\Scripts\python -m rl_analyzer doctor --live`, then `.venv\Scripts\python -m rl_analyzer preview`. Inspect `out/tweet.txt` and `out/last_run.json`; no database write or post occurs.
5. Keep `POST_TO_X=false` for manual delivery. To post live, first follow [X setup and pricing](docs/SETUP_X.md) and obtain explicit authorization for a deliberate test.

## Commands

```powershell
.venv\Scripts\python -m rl_analyzer run [--dry-run] [--force] [--verbose]
.venv\Scripts\python -m rl_analyzer preview [--replay-id ID] [--verbose]
.venv\Scripts\python -m rl_analyzer demo
.venv\Scripts\python -m rl_analyzer doctor [--offline | --live]
.venv\Scripts\python -m rl_analyzer history [--limit 10]
```

`run` exits 0 when no new eligible replay exists. Manual mode writes `out/tweet.txt`, `out/last_run.json` and a timestamped `out/history/` copy, prints it and optionally copies it. `preview`/`--dry-run` bypass cooldown, do not write the DB and never post. `--force` bypasses only the 20-hour cooldown, not dedupe or in-flight guards. Exit codes: 0 success/no-op; 2 config; 3 ballchasing; 4 AI; 5 post; 6 lock/storage/unknown.

## Schedule for 19:00 local

From PowerShell in the repo, preview the operation, then install only when ready:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install_task.ps1 -WhatIf
powershell -ExecutionPolicy Bypass -File scripts/install_task.ps1
powershell -ExecutionPolicy Bypass -File scripts/uninstall_task.ps1
```

The installer updates `RL Analyzer Daily` rather than duplicating it; it uses `StartWhenAvailable`, `IgnoreNew` and a one-hour execution limit. Run under the intended user account and keep the session available if clipboard access is needed. The wrapper writes timestamped stdout/stderr to `logs/scheduler.log` and returns Python's exit code. Actual task registration was not performed during development.

Alternatively, from **Command Prompt** in the repository (the `/F` option replaces an existing task of this name):

```cmd
schtasks /Create /TN "RL Analyzer Daily" /SC DAILY /ST 19:00 /TR "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"%CD%\scripts\run_daily.ps1\"" /F
schtasks /Delete /TN "RL Analyzer Daily" /F
```

## Files and troubleshooting

`src/rl_analyzer/` contains the CLI and modules; `tests/` has offline fixtures/tests; `scripts/` has scheduler scripts; `docs/` contains guides, decisions and checkpoints. `data/`, `logs/`, `out/`, `.env` and `.venv/` are gitignored.

- No candidate: verify upload visibility, the three IDs, 3v3 same-team status, allowed playlist, and 48-hour freshness window.
- If an upload lacks both match GUID and Rocket League ID, only its replay ID is available; separate uploads with no shared match identifier cannot be reliably recognized as the same match.
- AI failure: verify the model/service or provider key; the app never substitutes a template.
- Clipboard unavailable: the output file is still written.
- X rejection: check the safe HTTP status and guidance in the console or `logs/rl_analyzer.log`; see [X troubleshooting](docs/SETUP_X.md). Confirmed failures retain the cached tweet without another AI call.
- Doctor reports an in-flight post or analysis: stop and inspect manually. An uncertain post may already exist on X; do not blindly retry or alter the DB. `--force` will not bypass the guard.
- Scheduler issue: inspect `logs/scheduler.log`, task account, working directory and 19:00 local trigger. See [manual test](docs/MANUAL_TEST.md).
