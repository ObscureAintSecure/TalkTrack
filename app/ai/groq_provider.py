"""Groq (groq.com) API provider — GroqCloud inference via the official SDK.

Not to be confused with `grok_provider.py` (Grok, xAI).
"""

from app.ai.provider import AIProvider


class GroqProvider(AIProvider):
    embed_model_id = "st:all-MiniLM-L6-v2"

    def __init__(self, api_key: str, model: str = "openai/gpt-oss-120b"):
        from groq import Groq
        self._client = Groq(
            api_key=api_key,
            timeout=120.0,
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
        from app.ai.provider import get_sentence_transformer
        model = get_sentence_transformer("all-MiniLM-L6-v2")
        embeddings = model.encode(texts)
        return [e.tolist() for e in embeddings]
