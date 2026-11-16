"""Provider interface and safe errors for AI generation."""

from abc import ABC, abstractmethod
from contextlib import contextmanager
import logging
import time
from typing import Any, Callable, Iterator
from urllib.parse import quote, quote_plus

import requests


class AIError(RuntimeError):
    """An AI provider failed; its message must never contain secrets."""


class AIValidationError(AIError):
    """Invalid AI text with a strictly allow-listed diagnostic category."""

    def __init__(self, reason: str) -> None:
        allowed = {"empty_or_short", "refusal", "score", "player_name", "length", "format", "invalid_output"}
        self.reason = reason if reason in allowed else "invalid_output"
        super().__init__("AI output failed tweet validation after retry")


class AIProvider(ABC):
    """Synchronous text-generation provider."""

    @abstractmethod
    def generate(self, system: str, user: str) -> str:
        """Generate one tweet candidate or raise AIError."""


class _SecretFilter(logging.Filter):
    """Redact credentials from underlying HTTP debug records, including URLs."""

    def __init__(self, secrets: list[str]) -> None:
        super().__init__()
        self.secrets = sorted({part for secret in secrets if secret for part in
                               (secret, quote(secret, safe=""), quote_plus(secret))}, key=len, reverse=True)

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = message
        for secret in self.secrets:
            redacted = redacted.replace(secret, "[REDACTED]")
        if redacted != message:
            record.msg, record.args = redacted, ()
        return True


@contextmanager
def _protect_http_logs(secrets: list[str]) -> Iterator[None]:
    """Protect common requests/urllib3 debug logs during synchronous calls."""
    filter_ = _SecretFilter(secrets)
    loggers = [logging.getLogger(name) for name in ("requests", "urllib3.connectionpool", "urllib3.util.retry")]
    for logger in loggers:
        logger.addFilter(filter_)
    try:
        yield
    finally:
        for logger in loggers:
            logger.removeFilter(filter_)


class JsonHTTPClient:
    """Send JSON with bounded retries and sanitized provider errors."""

    def __init__(self, *, timeout: float, session: requests.Session | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._timeout = timeout
        self._session = session if session is not None else requests.Session()
        self._sleep = sleep

    def post(self, url: str, *, body: dict[str, Any], headers: dict[str, str] | None = None,
             params: dict[str, str] | None = None) -> dict[str, Any]:
        """Retry only rate-limit and server responses, never exposing response text."""
        headers, params = headers or {}, params or {}
        secrets = [value for key, value in headers.items() if key.lower() in {"authorization", "x-api-key", "x-goog-api-key"}]
        secrets.extend(value[7:] for value in list(secrets) if value.lower().startswith("bearer "))
        secrets.extend(value for key, value in params.items() if key.lower() in {"key", "api_key", "access_token"})
        for attempt in range(4):
            try:
                with _protect_http_logs(secrets):
                    response = self._session.post(url, json=body, headers=headers, params=params, timeout=self._timeout)
            except requests.RequestException:
                raise AIError("AI provider request failed; check connectivity") from None
            status = response.status_code
            if status == 429 or 500 <= status <= 599:
                if attempt == 3:
                    raise AIError(f"AI provider HTTP {status}; retries exhausted")
                self._sleep(2 ** attempt)
                continue
            if not 200 <= status < 300:
                raise AIError(f"AI provider HTTP {status}")
            try:
                value = response.json()
            except ValueError:
                raise AIError("AI provider returned invalid JSON") from None
            if not isinstance(value, dict):
                raise AIError("AI provider returned an invalid JSON object")
            return value
        raise AssertionError("unreachable")
