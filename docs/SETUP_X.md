# X setup

## Cost and safety

X API access is pay-per-usage and requires credits; do not assume a free API tier. On **2026-10-30**, [X's official pricing](https://docs.x.com/x-api/getting-started/pricing) listed **$0.015 per create-post request** and **$0.200 with a URL**. A 30-day month at one text-only request/day is about **$0.45**, excluding taxes or other usage. Prices change; check the [Developer Console](https://console.x.com/) before enabling posting. Promotional credits may have conditions; they are not a guaranteed free tier. The app rejects URLs in tweets.

## OAuth 1.0a (default)

1. Create an X developer account and an app; add credits and set an appropriate spending limit.
2. Set the app permissions to **Read and write before generating the access token**. If permissions change, regenerate the access token and secret.
3. Store the app API key and secret as `X_API_KEY` and `X_API_SECRET`; store the user access token and secret as `X_ACCESS_TOKEN` and `X_ACCESS_SECRET`. Set `X_AUTH_MODE=oauth1`.
4. Keep `POST_TO_X=false` while running `demo`, `doctor`, and `preview`. Inspect `out/tweet.txt`. Only after an explicitly authorized deliberate live test, set `POST_TO_X=true`; then a real `run` can incur charges. `--force` bypasses cooldown only, not deduplication or posting guards.

## OAuth2 fallback

Set `X_AUTH_MODE=oauth2` and `X_OAUTH2_USER_TOKEN` to a valid **user-context** access token with the necessary posting permissions/scopes. An app-only bearer token cannot post for a user. Tokens expire; obtain or refresh the token manually and update `.env`. The app does not implement an OAuth consent or refresh flow.

The app sends only `POST /2/tweets` with text. It makes no media uploads, threads, replies or quote posts. Confirmed failures retain cached text; timeouts and other uncertain outcomes remain blocked for inspection to avoid duplicate posts. Never expose `.env`, tokens, authorization headers or the SQLite database. See [X app permissions](https://docs.x.com/fundamentals/developer-apps) and [authentication](https://docs.x.com/fundamentals/authentication/overview).

## Troubleshooting a failed post

The console and `logs/rl_analyzer.log` report a numeric HTTP status and fixed guidance when X returns a rejection; they never include response bodies or credentials. Earlier logs that only say `X posting failed; cached text retained` did not preserve the status, so their exact cause cannot be determined from that message alone.

- **401:** check that the API key/secret and the OAuth 1.0a user access token/secret all belong to the same app; regenerate tokens if needed.
- **403:** check that the app has **Read and write** permission, regenerate the user access token and secret after changing permissions, and verify the app's API access and credit balance. A 403 does not by itself prove which of these is wrong.
- When X supplies a documented problem type, `client-forbidden` means the app is not enrolled or lacks endpoint access; `usage-capped` points to an API usage/spending cap; `not-authorized-for-resource` points to user/resource authorization. X may instead return only a generic 403.
- **402:** check API credits and billing. **429:** wait for the rate limit to reset.
- **5xx, timeout, or invalid success response:** the result may be unknown. `doctor --offline` reports a `posting` guard; inspect the X account before any manual resolution. Do not blindly retry.

A confirmed rejection keeps the exact cached text as `generated`, so a later authorized run can retry without another AI call while the replay is fresh. If it expires, the app skips that cached entry and may select another replay. Do not share credentials, Authorization headers, response bodies or private replay data when requesting help.

Reference: [X response codes and problem types](https://docs.x.com/x-api/fundamentals/response-codes-and-errors). X's [authentication mapping](https://docs.x.com/fundamentals/authentication/guides/v2-authentication-mapping) lists OAuth 1.0a user context as supported for `POST /2/tweets`.
