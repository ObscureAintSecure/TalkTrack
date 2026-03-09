"""Grok (xAI) API provider — uses OpenAI-compatible API."""

from app.ai.provider import AIProvider


class GrokProvider(AIProvider):
    def __init__(self, api_key: str, model: str = "grok-3"):
        from openai import OpenAI
        self._client = OpenAI(
            api_key=api_key,
            base_url="https://api.x.ai/v1",
        )
        self._model = model

    def complete(self, prompt: str, context: str = "") -> str:
        messages = []
        if context:
            messages.append({"role": "system", "content": context})
        messages.append({"role": "user", "content": prompt})

        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
        )
        return response.choices[0].message.content

    def embed(self, texts: list[str]) -> list[list[float]]:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")
        embeddings = model.encode(texts)
        return [e.tolist() for e in embeddings]
