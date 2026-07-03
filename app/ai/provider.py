"""Base class for AI providers."""

from abc import ABC, abstractmethod

# Loaded SentenceTransformer models keyed by name. Model init costs seconds
# (and a download on first use); embed() may be called per search.
_SENTENCE_TRANSFORMER_CACHE = {}


def get_sentence_transformer(model_name: str):
    if model_name not in _SENTENCE_TRANSFORMER_CACHE:
        from sentence_transformers import SentenceTransformer
        _SENTENCE_TRANSFORMER_CACHE[model_name] = SentenceTransformer(model_name)
    return _SENTENCE_TRANSFORMER_CACHE[model_name]


class AIProvider(ABC):
    # Character budget for transcript context in prompts. Cloud models have
    # 100k+ token windows; local models override with their real n_ctx limit.
    max_context_chars = 100_000

    # Identity of the model embed() uses — the key for on-disk embedding
    # caches (#33). None disables caching for the provider. Must change
    # whenever the vectors would (different model = incompatible vectors).
    embed_model_id = None

    @abstractmethod
    def complete(self, prompt: str, context: str = "") -> str:
        ...

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        ...

    def test_connection(self) -> bool:
        try:
            result = self.complete("Say 'ok'.", "")
            return bool(result)
        except Exception:
            return False
