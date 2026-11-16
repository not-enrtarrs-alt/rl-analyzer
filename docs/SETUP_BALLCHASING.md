# Ballchasing setup

1. Sign in at [ballchasing.com](https://ballchasing.com/) and retrieve or generate an API token on its [upload page](https://ballchasing.com/upload). Put it in `BALLCHASING_TOKEN` in the local `.env`; do not share it or paste it into logs.
2. Open each player's ballchasing profile. Copy the profile URL `https://ballchasing.com/player/<platform>/<id>` into `PLAYER_1_ID`, `PLAYER_2_ID`, and `PLAYER_3_ID`, or use `platform:id`. Set three nonempty aliases. Players must be distinct; display names alone are not identifiers. `psn` is normalized to `ps4`.
3. Someone with a replay file must upload it. Ballchasing does **not** automatically ingest games. Private or unlisted uploads may not be visible to another account or its API token. Confirm the replay is visible to the configured account, processed successfully, 3v3, and on an allowed playlist.
4. Run `.venv\Scripts\python -m rl_analyzer doctor --live`, then `preview` with `POST_TO_X=false`. Review `out/tweet.txt` and `out/last_run.json`.

The app reads JSON stats only; it never downloads replay files. For non-patrons, ballchasing documents a maximum of 2 requests/second, 500 list requests/hour and 1,000 detail requests/hour. The default interval is 0.6 seconds; 429 and server errors are retried. The app queries all three players separately, intersects replay IDs, inspects at most `MAX_CANDIDATES_TO_INSPECT`, and ignores games older than `MAX_REPLAY_AGE_HOURS` (48 by default). A fresh game uploaded late may already be outside that window.

Match GUID and Rocket League ID are both checked when available. If an upload has neither, dedupe falls back to replay ID; separate uploads with no shared match identifier cannot be reliably linked.

References: [API documentation](https://ballchasing.com/doc/api), [upload and visibility FAQ](https://ballchasing.com/doc/faq).
