"""Mistral AI API provider."""

from app.ai.provider import AIProvider


class MistralProvider(AIProvider):
    def __init__(self, api_key: str, model: str = "mistral-large-latest"):
        from mistralai import Mistral
        self._client = Mistral(api_key=api_key)
        self._model = model

    def complete(self, prompt: str, context: str = "") -> str:
        messages = []
        if context:
            messages.append({"role": "system", "content": context})
        messages.append({"role": "user", "content": prompt})

        response = self._client.chat.complete(
            model=self._model,
            messages=messages,
        )
        return response.choices[0].message.content

    def embed(self, texts: list[str]) -> list[list[float]]:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")
        embeddings = model.encode(texts)
        return [e.tolist() for e in embeddings]
