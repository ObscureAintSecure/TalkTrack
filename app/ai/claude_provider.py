"""Claude API provider."""

from app.ai.provider import AIProvider


class ClaudeProvider(AIProvider):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        from anthropic import Anthropic
        # Explicit timeout — the SDK default (~10 min) leaves workers hung
        # on a dead network with no user-visible failure.
        self._client = Anthropic(api_key=api_key, timeout=120.0)
        self._model = model

    def complete(self, prompt: str, context: str = "") -> str:
        messages = []
        if context:
            messages.append({"role": "user", "content": context})
            messages.append({"role": "assistant", "content": "I've read the transcript. What would you like to know?"})
        messages.append({"role": "user", "content": prompt})

        response = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            messages=messages,
        )
        return response.content[0].text

    def embed(self, texts: list[str]) -> list[list[float]]:
        from app.ai.provider import get_sentence_transformer
        model = get_sentence_transformer("all-MiniLM-L6-v2")
        embeddings = model.encode(texts)
        return [e.tolist() for e in embeddings]
