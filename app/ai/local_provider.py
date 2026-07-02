"""Local model provider using llama-cpp-python and sentence-transformers."""

from app.ai.provider import AIProvider


class LocalProvider(AIProvider):
    # llama-cpp runs with n_ctx=4096 tokens; ~8k chars leaves room for the
    # instruction and the completion.
    max_context_chars = 8_000

    def __init__(self, model_path: str, embed_model: str = "all-MiniLM-L6-v2"):
        self._model_path = model_path
        self._embed_model_name = embed_model
        self._llm = None

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
        from app.ai.provider import get_sentence_transformer
        return get_sentence_transformer(self._embed_model_name)

    def complete(self, prompt: str, context: str = "") -> str:
        llm = self._get_llm()
        full_prompt = f"{context}\n\n{prompt}" if context else prompt
        response = llm(full_prompt, max_tokens=2048)
        return response["choices"][0]["text"].strip()

    def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._get_embedder()
        embeddings = model.encode(texts)
        return [e.tolist() for e in embeddings]
