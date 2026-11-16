"""Local Ollama chat provider."""

from ..config import Config
from .base import AIError, AIProvider, JsonHTTPClient


class OllamaProvider(AIProvider):
    """Generate a single response with Ollama's non-streaming chat API."""

    def __init__(self, config: Config, *, http: JsonHTTPClient | None = None) -> None:
        self._config = config
        self._http = http if http is not None else JsonHTTPClient(timeout=config.request_timeout_seconds)

    def generate(self, system: str, user: str) -> str:
        config = self._config
        data = self._http.post(f"{config.ollama_base_url.rstrip('/')}/api/chat", body={
            "model": config.ollama_model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False, "options": {"temperature": config.ai_temperature, "num_predict": config.ai_max_output_tokens},
        })
        message = data.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise AIError("Ollama returned no text")
        return content
