# Manual test

Do not perform a live X test without explicit authorization. Do not delete or reset an existing database to test.

For the CLI subcommands below, use `.venv\Scripts\python -m rl_analyzer` followed by the command and flags.

- [✓] Run `.venv\Scripts\python -m pytest -q`: all tests pass without network access.
- [✓] With no credentials, run `doctor --offline`: exit 0 and missing credentials appear as warnings; no network call or X post occurs.
- [✓] Run `demo`: `out/demo_tweet.txt` exists, has one score/name and exactly one `#RocketLeague`, and is at most 280 weighted characters. Demo uses a fixture and mock AI, no database or network.
- [✓] Configure ballchasing and an AI provider with `POST_TO_X=false`. Run `doctor --live`: ballchasing and Ollama checks report their status; no X post is attempted. A non-Ollama provider may still produce an Ollama warning.
- [✓] Run `preview` or `preview --replay-id ID`: a fresh eligible match writes `out/tweet.txt`, `out/last_run.json` and `out/history/`; clipboard is copied if enabled. No DB writes or X post. Review stats and tone.
- [✓] Run `run` in manual mode: valid output is saved and the match is recorded as generated. A second immediate `run` exits 0 without a new AI call because of cooldown. `--force` bypasses cooldown, not match dedupe.
- [✓] Run `history --limit 10`: entries show UTC match date, result/score, status, tweet ID and preview. No credentials are printed.
- [✓] Run the installer with `-WhatIf`: the intended task is `RL Analyzer Daily` at 19:00 local. Install only when ready; rerunning the installer updates the task. Check Task Scheduler settings and `logs/scheduler.log` after a scheduled run.
- [✓] If doctor reports a `posting` or analysis-in-progress row, stop and inspect manually. Check X for a possible existing post; do not force or blindly retry an uncertain outcome.

Optional live posting is **not part of development testing**. If separately authorized, review [SETUP_X.md](SETUP_X.md), credits and permissions first. A successful post is archived under `out/posted/`; a rejected post retains cached text for later, while an uncertain outcome requires inspection.
