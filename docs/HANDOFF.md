# Handoff

## Status

M6 is complete and checkpointed: a real-data non-posting preview succeeded. See `CHECKPOINTS/M6.md`. Post-M6, the user reported repeated HTTP 403 responses when posting; prior response problem types were not saved, so the exact cause remains unknown.

## Verified

- `.venv\Scripts\python.exe -m pytest -q`: 310 tests pass without network access; `pip check` reports no broken requirements.
- `doctor --offline` exits 0 with three configured players and reports the user's current X-enabled configuration without exposing credentials. Earlier `doctor --live` authenticated to ballchasing and found the configured Ollama model; it did not call X.
- Ballchasing client, selection and stats work together with mocked HTTP and synthetic data; selected detail is reused by callers.
- SQLite schema, canonical-key dedupe/reservations, capped retries, cached post state, cooldown, and read-only access are tested with temporary databases, including concurrent reservations.
- M6 audit fixed deduplication across uploads where only one carries a match GUID but both share a Rocket League ID; tests cover partial identifiers, casing, concurrent reservations and no duplicate AI call.
- Four AI providers, mock generation, tweet sanitization, weighted validation and the single invalid-output retry are tested offline with fake HTTP.
- A real-data preview using local Ollama and a temporary 30-day freshness window wrote a validated 235-weighted-character tweet to `out/tweet.txt`; DB unchanged, clipboard and X disabled. The first real attempt failed safely; the next succeeded after prompt hardening.
- `python -m rl_analyzer demo` produced `out/demo_tweet.txt` (82 weighted characters); clipboard was disabled for the acceptance run. Run/preview, manual output, cached retries and X behavior are tested with fake services.
- Doctor reports posting and analysis guards; history reads existing databases without creating or modifying them. Scheduler scripts pass mocked execution tests and a real Windows `-WhatIf` check. No task was installed.
- X pricing was verified against official documentation on 2026-10-30 and recorded in `SETUP_X.md`; verify again before enabling live posting.
- Python 3.11.4; editable project installed in `.venv`. Local ignored `.env` contains user-supplied credentials and IDs and currently enables X posting; never print, commit or change it without authorization.
- The reported failed tweet remains generated, locally valid and fresh, with no in-flight guard and no successful posts recorded in this DB. OAuth1 request preparation succeeded locally; this does not verify X authorization or billing. No X request was made by the assistant.
- X failures now report a validated HTTP status, fixed guidance, and documented exact-match problem types when supplied. Free-form response details, credentials and arbitrary exception messages are not logged. Confirmed failures retain the cached text; unknown outcomes stay guarded.
- X's official authentication mapping lists OAuth 1.0a user context for `POST /2/tweets`; the user's configured auth mode was not changed.

## Untested / known limitations

- Actual Task Scheduler registration/execution and a real clipboard copy were not tested; the task installer was exercised with mocks and `-WhatIf` only.
- OpenAI, Anthropic, Gemini and X authentication have not been verified live by the assistant. Semantic correctness of result/standout/roast/boost or demo details is prompted rather than independently verified; inspect the preview before using it.
- A crashed analysis remains `analysis_failed` with `reason=analysis_in_progress`; it blocks automatic reanalysis until inspected. A `posting` row blocks further live posts, and `posting_unknown` must not be automatically retried. These deliberate safety choices are documented in `DECISIONS.md`.
- Result/score, cached player names and manual-delivery timestamp extend the supplied schema. Existing version-1 databases gain these nullable columns on writable open. Cached legacy rows without enough metadata fail safe instead of posting unvalidated text. Actual live API, clipboard and scheduler behavior remain untested.
- No X post or scheduled task installation was performed by the assistant. The default Ollama model is installed. The user-set freshness window is 480 hours and local request timeout is 120 seconds; aliases can be customized privately.
- `select.match_key` must fall back to replay ID when both match identifiers are missing. Distinct uploads without any shared identifier cannot be reliably linked; this limitation is documented in `README.md`, `SPEC.md` and `SETUP_BALLCHASING.md`.

## Conventions and next step

Follow the complete session-start protocol in `../rl-analyzer-prompt.txt`, redo environment discovery, and work one tested sub-step at a time. Keep credentials out of logs, use UTC, append progress after each sub-step, and checkpoint milestones before continuing. Do not post to X.

The pipeline uses read-only DB access for preview/dry-run, reserves canonical match keys before AI, revalidates cached text, and never automatically retries uncertain X outcomes. Mock-generated tweets cannot be posted live. Keep these invariants and do not perform a live X test without explicit user authorization.

Next: check X developer-account credit balance and that the app is enrolled for the create-post endpoint. If the user deliberately chooses to retry, `run --force` can post the fresh cached tweet and may report an allow-listed problem type; it can select a different replay if the cached one expires. Request only the safe error line, never credentials or response bodies. Do not post to X or install a scheduled task on the user's behalf without explicit authorization.
