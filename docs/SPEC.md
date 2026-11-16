# Specification

The full authoritative specification is `../rl-analyzer-prompt.txt`.

- **Selection:** three configured platform IDs, separate ballchasing list queries and intersection; inspect newest 3v3 same-team game in the freshness window and playlist allow-list. Older games remain eligible. Stats use available JSON values; missing optional values remain null.
- **Identity and storage:** SQLite deduplicates by match GUID, then Rocket League ID, then replay ID. Analysis reservations, capped retries, generated/posting/posted/skipped states and a 20-hour success cooldown prevent duplicate processing. `--force` bypasses cooldown only.
- **AI and tweet:** Ollama by default, OpenAI/Anthropic/Gemini alternatives, explicit mock for tests/demo. Sanitize and validate one English text-only tweet with score, a player name and optional configured hashtag, at most 280 conservative weighted characters. One invalid-output retry; no template fallback.
- **Delivery:** manual file, history and optional clipboard by default. X OAuth1/OAuth2 posting is opt-in. Confirmed failures retain the cached text; uncertain post outcomes remain guarded. No media, replies or threads.
- **Commands:** `run`, `preview`, `demo`, `doctor`, `history`. Preview/dry-run do not write the database or post. Repeated previews of an unconsumed game can call AI again because they do not persist state. Demo uses only a bundled synthetic fixture.
- **Scheduling:** Windows Task Scheduler at 19:00 local. The wrapper logs to `logs/scheduler.log`. No task was installed and no live X post was made during development.

**Limitations:** provider calls and X authentication have not been live-tested. If distinct uploads lack a shared match GUID or Rocket League ID, replay-ID fallback cannot recognize them as the same match. Validation checks score, player name and format, but cannot independently prove the AI's result description, roast, or every stat claim; inspect previews. A crashed analysis or uncertain post remains blocked for manual inspection. See `DECISIONS.md` for schema extensions and safety choices.
