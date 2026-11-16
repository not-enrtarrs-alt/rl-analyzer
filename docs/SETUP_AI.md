# AI setup

## Ollama (default)

1. Install [Ollama for Windows](https://ollama.com/download/windows).
2. In PowerShell run `ollama pull llama3.1:8b`, then `ollama serve`. If the Windows app already runs the service, do not start a second instance.
3. Keep `AI_PROVIDER=ollama`, `OLLAMA_BASE_URL=http://localhost:11434`, and `OLLAMA_MODEL=llama3.1:8b`, or choose another installed model. `ollama list` shows installed models. Model downloads and local inference require sufficient disk space and memory.
4. `doctor --live` checks whether the Ollama API and configured model are available; `preview` makes an actual generation request but does not post or write the database.

## Hosted alternatives

Set `AI_PROVIDER=openai`, `anthropic`, or `gemini`; put only that provider's key in `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `GEMINI_API_KEY`, and set its model in `.env`. Provider base URLs are configurable in `.env.example`. Hosted services may charge for requests and receive the trio's match statistics and aliases. Check their current pricing and privacy terms. Never share `.env` or print its contents.

`AI_PROVIDER=mock` is deterministic and intended only for tests, demo and previews; mock-generated text cannot be posted live. Invalid output is retried once with a shorter instruction. Provider or validation failure is skipped safely; there is no template fallback. Even valid output can misrepresent stats: review previews before enabling posting.
