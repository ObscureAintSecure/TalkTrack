"""Google Gemini API provider."""

from app.ai.provider import AIProvider


class GeminiProvider(AIProvider):
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(model)

    def complete(self, prompt: str, context: str = "") -> str:
        full_prompt = f"{context}\n\n{prompt}" if context else prompt
        response = self._model.generate_content(full_prompt)
        return response.text

    def embed(self, texts: list[str]) -> list[list[float]]:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")
        embeddings = model.encode(texts)
        return [e.tolist() for e in embeddings]
