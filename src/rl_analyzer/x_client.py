"""X API v2 text-only posting with no automatic retries."""

from typing import Any

import requests
from requests_oauthlib import OAuth1Session

from .ai.base import _protect_http_logs
from .config import Config
from .tweet import TweetError, validate_delivery_text

_PROBLEMS = {
    "client-forbidden": "app is not enrolled or lacks required endpoint access; check developer account and app access",
    "usage-capped": "API usage cap reached; check the spending limit and credits",
    "not-authorized-for-resource": "account is not authorized for this action or resource; check user permissions",
    "rate-limit-exceeded": "API rate limit exceeded; retry later",
}
_PROBLEM_URLS = {f"https://{host}/2/problems/{name}": name
                 for host in ("api.x.com", "api.twitter.com") for name in _PROBLEMS}


def _classify_problem(response: Any) -> str | None:
    """Extract only documented, exact-match problem types; discard all other data."""
    try:
        body = response.json()
    except (ValueError, TypeError, AttributeError):
        return None
    if not isinstance(body, dict):
        return None
    candidates = [body]
    errors = body.get("errors")
    if isinstance(errors, list):
        candidates.extend(item for item in errors[:10] if isinstance(item, dict))
    for item in candidates:
        value = item.get("type")
        if isinstance(value, str) and value in _PROBLEM_URLS:
            return _PROBLEM_URLS[value]
    return None


class XError(RuntimeError):
    """A safe X error with explicit certainty about whether a post occurred."""

    def __init__(self, message: str, *, outcome_known: bool, status_code: int | None = None,
                 category: str | None = None, problem: str | None = None) -> None:
        super().__init__(message)
        self.outcome_known = outcome_known
        self.status_code = status_code if type(status_code) is int and 100 <= status_code <= 599 else None
        self.category = category if isinstance(category, str) and category in {"disabled", "invalid_text", "missing_credentials", "invalid_auth", "transport", "invalid_response"} else None
        self.problem = problem if isinstance(problem, str) and problem in _PROBLEMS else None

    def safe_diagnostic(self) -> str:
        """Return only fixed guidance and a validated numeric status, never server text."""
        guidance = {
            400: "invalid request; check the X developer console",
            401: "authentication failed; check the app keys and user access tokens",
            402: "payment required; check X API credits and billing",
            403: "access denied; verify Read and write permissions, regenerate user tokens, and check app access and credits",
            404: "endpoint not found; check the X API base URL and app access",
            429: "rate limited; retry later",
        }
        if self.status_code is not None and self.problem:
            return f"X HTTP {self.status_code} ({self.problem}): {_PROBLEMS[self.problem]}"
        if self.status_code is not None:
            suffix = guidance.get(self.status_code, "server error" if self.status_code >= 500 else "request failed")
            return f"X HTTP {self.status_code}: {suffix}"
        return {
            "disabled": "X posting is disabled",
            "invalid_text": "tweet failed text-only safety validation",
            "missing_credentials": "X credentials are incomplete",
            "invalid_auth": "X authentication mode is invalid",
            "transport": "X connection failed",
            "invalid_response": "X returned an invalid success response",
        }.get(self.category, "X posting failed")


class XClient:
    """Send one validated text post using OAuth 1.0a or a user bearer token."""

    def __init__(self, config: Config, *, session: Any = None) -> None:
        self._config = config
        self._session = session

    def post(self, text: str) -> str:
        """Return the new post ID; never retry an uncertain or rejected request."""
        config = self._config
        if not config.post_to_x:
            raise XError("X posting is disabled", outcome_known=True, category="disabled")
        try:
            validate_delivery_text(text, hashtag=config.tweet_hashtag,
                                   max_weighted_len=config.tweet_max_weighted_len,
                                   allow_emoji=config.tweet_allow_emoji)
        except TweetError:
            raise XError("Tweet failed text-only safety validation", outcome_known=True, category="invalid_text") from None
        secrets = [config.x_api_key, config.x_api_secret, config.x_access_token,
                   config.x_access_secret, config.x_oauth2_user_token]
        headers: dict[str, str] = {}
        if config.x_auth_mode == "oauth1":
            if not all(secrets[:4]):
                raise XError("Missing OAuth 1.0a credentials", outcome_known=True, category="missing_credentials")
            session = self._session if self._session is not None else OAuth1Session(
                client_key=config.x_api_key, client_secret=config.x_api_secret,
                resource_owner_key=config.x_access_token, resource_owner_secret=config.x_access_secret)
        elif config.x_auth_mode == "oauth2":
            if not config.x_oauth2_user_token:
                raise XError("Missing OAuth2 user token", outcome_known=True, category="missing_credentials")
            session = self._session if self._session is not None else requests.Session()
            headers["Authorization"] = f"Bearer {config.x_oauth2_user_token}"
        else:
            raise XError("Invalid X authentication mode", outcome_known=True, category="invalid_auth")
        try:
            with _protect_http_logs(secrets):
                response = session.post(f"{config.x_api_base_url.rstrip('/')}/2/tweets",
                                        json={"text": text}, headers=headers, timeout=config.request_timeout_seconds)
        except requests.RequestException:
            raise XError("X request failed; post outcome is unknown", outcome_known=False, category="transport") from None
        status = response.status_code
        if status != 201:
            if status in (401, 403):
                raise XError(f"X HTTP {status}; check credentials and write permissions", outcome_known=True,
                             status_code=status, problem=_classify_problem(response))
            if status == 429:
                raise XError("X HTTP 429; rate limited", outcome_known=True, status_code=status,
                             problem=_classify_problem(response))
            raise XError(f"X HTTP {status}", outcome_known=400 <= status < 500 and status != 408, status_code=status)
        try:
            tweet_id = response.json()["data"]["id"]
        except (ValueError, KeyError, TypeError):
            raise XError("X returned an invalid success response; post outcome is unknown", outcome_known=False, category="invalid_response") from None
        if not isinstance(tweet_id, str) or not tweet_id.strip():
            raise XError("X returned no post ID; post outcome is unknown", outcome_known=False, category="invalid_response")
        return tweet_id
