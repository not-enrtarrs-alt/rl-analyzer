"""Google Gemini generateContent provider."""

from urllib.parse import quote

from ..config import Config
from .base import AIError, AIProvider, JsonHTTPClient


class GeminiProvider(AIProvider):
    """Generate text with Gemini's configured model and API base."""

    def __init__(self, config: Config, *, http: JsonHTTPClient | None = None) -> None:
        self._config = config
        self._http = http if http is not None else JsonHTTPClient(timeout=config.request_timeout_seconds)

    def generate(self, system: str, user: str) -> str:
        config = self._config
        model = quote(config.gemini_model, safe="")
        data = self._http.post(f"{config.gemini_base_url.rstrip('/')}/models/{model}:generateContent",
            params={"key": config.gemini_api_key}, body={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"temperature": config.ai_temperature, "maxOutputTokens": config.ai_max_output_tokens},
            })
        try:
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError):
            raise AIError("Gemini returned no text") from None
        if not isinstance(parts, list):
            raise AIError("Gemini returned no text")
        content = "\n".join(part["text"] for part in parts if isinstance(part, dict) and not part.get("thought") and isinstance(part.get("text"), str))
        if not content.strip():
            raise AIError("Gemini returned no text")
        return content
