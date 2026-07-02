# tests/test_ai_provider.py
import unittest
from unittest.mock import patch, MagicMock
import sys


class TestProviderFactory(unittest.TestCase):
    def test_create_claude_provider(self):
        mock_anthropic = MagicMock()
        with patch.dict(sys.modules, {"anthropic": mock_anthropic}):
            from app.ai.provider_factory import create_provider
            from app.ai.claude_provider import ClaudeProvider
            # Reload to pick up the mock
            import importlib
            import app.ai.claude_provider
            importlib.reload(app.ai.claude_provider)
            from app.ai.claude_provider import ClaudeProvider

            config = {"provider": "claude", "api_key": "test-key", "model": "claude-sonnet-4-6"}
            provider = create_provider(config)
            self.assertIsInstance(provider, ClaudeProvider)

    def test_create_openai_provider(self):
        mock_openai = MagicMock()
        with patch.dict(sys.modules, {"openai": mock_openai}):
            from app.ai.provider_factory import create_provider
            import importlib
            import app.ai.openai_provider
            importlib.reload(app.ai.openai_provider)
            from app.ai.openai_provider import OpenAIProvider

            config = {"provider": "openai", "api_key": "test-key", "model": "gpt-4o"}
            provider = create_provider(config)
            self.assertIsInstance(provider, OpenAIProvider)

    def test_create_unknown_provider_raises(self):
        from app.ai.provider_factory import create_provider
        config = {"provider": "unknown"}
        with self.assertRaises(ValueError):
            create_provider(config)

    def test_create_none_provider(self):
        from app.ai.provider_factory import create_provider
        config = {"provider": "none"}
        provider = create_provider(config)
        self.assertIsNone(provider)

    def test_create_local_provider_uses_local_model_path(self):
        from app.ai.provider_factory import create_provider
        config = {
            "provider": "local",
            "model": "(set path below)",
            "local_model_path": "C:/models/test.gguf",
        }
        provider = create_provider(config)
        self.assertEqual(provider._model_path, "C:/models/test.gguf")

    def test_create_local_provider_falls_back_to_model_key(self):
        from app.ai.provider_factory import create_provider
        config = {
            "provider": "local",
            "model": "C:/models/legacy.gguf",
            "local_model_path": "",
        }
        provider = create_provider(config)
        self.assertEqual(provider._model_path, "C:/models/legacy.gguf")


class TestClaudeProvider(unittest.TestCase):
    def test_complete(self):
        mock_anthropic = MagicMock()
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Summary of meeting")]
        mock_client.messages.create.return_value = mock_response

        with patch.dict(sys.modules, {"anthropic": mock_anthropic}):
            import importlib
            import app.ai.claude_provider
            importlib.reload(app.ai.claude_provider)
            from app.ai.claude_provider import ClaudeProvider

            provider = ClaudeProvider(api_key="test", model="claude-sonnet-4-6")
            result = provider.complete("Summarize this", "transcript text")
            self.assertEqual(result, "Summary of meeting")
            mock_client.messages.create.assert_called_once()


class TestOpenAIProvider(unittest.TestCase):
    def test_complete(self):
        mock_openai = MagicMock()
        mock_client = MagicMock()
        mock_openai.OpenAI.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="AI response"))]
        mock_client.chat.completions.create.return_value = mock_response

        with patch.dict(sys.modules, {"openai": mock_openai}):
            import importlib
            import app.ai.openai_provider
            importlib.reload(app.ai.openai_provider)
            from app.ai.openai_provider import OpenAIProvider

            provider = OpenAIProvider(api_key="test", model="gpt-4o")
            result = provider.complete("Summarize", "transcript")
            self.assertEqual(result, "AI response")


class TestProviderInterface(unittest.TestCase):
    def test_base_class_is_abstract(self):
        from app.ai.provider import AIProvider
        with self.assertRaises(TypeError):
            AIProvider()

    def test_cloud_providers_have_generous_context_limit(self):
        from app.ai.provider import AIProvider
        self.assertGreaterEqual(AIProvider.max_context_chars, 50000)

    def test_local_provider_has_small_context_limit(self):
        from app.ai.local_provider import LocalProvider
        provider = LocalProvider(model_path="x.gguf")
        self.assertLessEqual(provider.max_context_chars, 10000)


class TestSentenceTransformerCache(unittest.TestCase):
    def test_same_model_name_loads_once(self):
        mock_st_module = MagicMock()
        with patch.dict(sys.modules, {"sentence_transformers": mock_st_module}):
            from app.ai import provider as provider_mod
            provider_mod._SENTENCE_TRANSFORMER_CACHE.clear()
            m1 = provider_mod.get_sentence_transformer("all-MiniLM-L6-v2")
            m2 = provider_mod.get_sentence_transformer("all-MiniLM-L6-v2")
        self.assertIs(m1, m2)
        self.assertEqual(mock_st_module.SentenceTransformer.call_count, 1)

    def test_claude_provider_embed_uses_shared_cache(self):
        mock_anthropic = MagicMock()
        mock_st_module = MagicMock()
        with patch.dict(sys.modules, {
            "anthropic": mock_anthropic,
            "sentence_transformers": mock_st_module,
        }):
            import importlib
            import app.ai.claude_provider
            importlib.reload(app.ai.claude_provider)
            from app.ai.claude_provider import ClaudeProvider
            from app.ai import provider as provider_mod
            provider_mod._SENTENCE_TRANSFORMER_CACHE.clear()

            p = ClaudeProvider(api_key="k", model="claude-sonnet-4-6")
            p.embed(["a"])
            p.embed(["b"])
        self.assertEqual(mock_st_module.SentenceTransformer.call_count, 1)


if __name__ == "__main__":
    unittest.main()
