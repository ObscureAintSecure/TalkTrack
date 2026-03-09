"""Local model provider using llama-cpp-python and sentence-transformers."""

from app.ai.provider import AIProvider


class LocalProvider(AIProvider):
    def __init__(self, model_path: str, embed_model: str = "all-MiniLM-L6-v2"):
        self._model_path = model_path
        self._embed_model_name = embed_model
        self._llm = None
        self._embedder = None

    def _get_llm(self):
        if self._llm is None:
            from llama_cpp import Llama
            self._llm = Llama(
                model_path=self._model_path,
                n_ctx=4096,
                n_threads=4,
            )
        return self._llm

    def _get_embedder(self):
        if self._embedder is None:
            from sentence_transformers import SentenceTransformer
            self._embedder = SentenceTransformer(self._embed_model_name)
        return self._embedder

    def complete(self, prompt: str, context: str = "") -> str:
        llm = self._get_llm()
        full_prompt = f"{context}\n\n{prompt}" if context else prompt
        response = llm(full_prompt, max_tokens=2048)
        return response["choices"][0]["text"].strip()

    def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._get_embedder()
        embeddings = model.encode(texts)
        return [e.tolist() for e in embeddings]
