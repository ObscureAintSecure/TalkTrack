# tests/test_ai_provider.py
import unittest
from unittest.mock import patch, MagicMock
import sys


# Shut down 2026-08-16 for free/developer tier (Groq deprecation notice of
# 2026-06-17). Requesting one returns 404 model_not_found.
DECOMMISSIONED_GROQ_MODELS = frozenset({
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
})


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

    def test_create_groq_provider(self):
        mock_groq = MagicMock()
        with patch.dict(sys.modules, {"groq": mock_groq}):
            from app.ai.provider_factory import create_provider
            import importlib
            import app.ai.groq_provider
            importlib.reload(app.ai.groq_provider)
            from app.ai.groq_provider import GroqProvider

            config = {"provider": "groq", "api_key": "test-key",
                      "model": "openai/gpt-oss-120b"}
            provider = create_provider(config)
            self.assertIsInstance(provider, GroqProvider)

    def test_groq_is_distinct_from_grok(self):
        """Groq (groq.com) and Grok (xAI) are different providers."""
        mock_groq = MagicMock()
        mock_openai = MagicMock()
        with patch.dict(sys.modules, {"groq": mock_groq, "openai": mock_openai}):
            from app.ai.provider_factory import create_provider
            import importlib
            import app.ai.groq_provider
            import app.ai.grok_provider
            importlib.reload(app.ai.groq_provider)
            importlib.reload(app.ai.grok_provider)
            from app.ai.groq_provider import GroqProvider
            from app.ai.grok_provider import GrokProvider

            groq = create_provider({"provider": "groq", "api_key": "k"})
            grok = create_provider({"provider": "grok", "api_key": "k"})
            self.assertIsInstance(groq, GroqProvider)
            self.assertIsInstance(grok, GrokProvider)
            self.assertNotIsInstance(groq, GrokProvider)

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


class TestGroqProvider(unittest.TestCase):
    def _provider(self, mock_groq, model="openai/gpt-oss-120b"):
        import importlib
        import app.ai.groq_provider
        importlib.reload(app.ai.groq_provider)
        from app.ai.groq_provider import GroqProvider
        return GroqProvider(api_key="test", model=model)

    def test_default_model_is_a_live_groq_model(self):
        """Groq decommissioned llama-3.3-70b-versatile / llama-3.1-8b-instant on
        2026-08-16; a dead default 404s on the first call (see issue below)."""
        import importlib
        import app.ai.groq_provider
        import inspect

        mock_groq = MagicMock()
        with patch.dict(sys.modules, {"groq": mock_groq}):
            importlib.reload(app.ai.groq_provider)
            from app.ai.groq_provider import GroqProvider
            default = inspect.signature(GroqProvider.__init__).parameters["model"].default

        self.assertNotIn(default, DECOMMISSIONED_GROQ_MODELS)
        self.assertEqual(default, "openai/gpt-oss-120b")

    def test_factory_default_is_a_live_groq_model(self):
        """provider_factory carries its own `model` default; if it drifts from the
        provider's, a config with no explicit model 404s on the first call."""
        import importlib
        import app.ai.groq_provider
        from app.ai.provider_factory import create_provider

        mock_groq = MagicMock()
        with patch.dict(sys.modules, {"groq": mock_groq}):
            importlib.reload(app.ai.groq_provider)
            provider = create_provider({"provider": "groq", "api_key": "test"})

        self.assertNotIn(provider._model, DECOMMISSIONED_GROQ_MODELS)
        self.assertEqual(provider._model, "openai/gpt-oss-120b")

    def test_complete(self):
        mock_groq = MagicMock()
        mock_client = MagicMock()
        mock_groq.Groq.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Groq response"))]
        mock_client.chat.completions.create.return_value = mock_response

        with patch.dict(sys.modules, {"groq": mock_groq}):
            provider = self._provider(mock_groq)
            result = provider.complete("Summarize", "transcript")

        self.assertEqual(result, "Groq response")
        kwargs = mock_client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "openai/gpt-oss-120b")
        self.assertEqual(kwargs["messages"][0]["role"], "system")
        self.assertEqual(kwargs["messages"][0]["content"], "transcript")
        self.assertEqual(kwargs["messages"][-1]["content"], "Summarize")

    def test_complete_without_context_sends_no_system_message(self):
        mock_groq = MagicMock()
        mock_client = MagicMock()
        mock_groq.Groq.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="x"))]
        mock_client.chat.completions.create.return_value = mock_response

        with patch.dict(sys.modules, {"groq": mock_groq}):
            provider = self._provider(mock_groq)
            provider.complete("Just this")

        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["role"], "user")

    def test_client_gets_explicit_timeout(self):
        """SDK defaults hang the worker and block app close (see ai-providers rule)."""
        mock_groq = MagicMock()
        with patch.dict(sys.modules, {"groq": mock_groq}):
            self._provider(mock_groq)
        kwargs = mock_groq.Groq.call_args.kwargs
        self.assertEqual(kwargs["api_key"], "test")
        self.assertEqual(kwargs["timeout"], 120.0)

    def test_embed_model_id_set_for_cache_keying(self):
        from app.ai.groq_provider import GroqProvider
        self.assertEqual(GroqProvider.embed_model_id, "st:all-MiniLM-L6-v2")

    def test_embed_uses_shared_sentence_transformer_cache(self):
        mock_groq = MagicMock()
        mock_st_module = MagicMock()
        with patch.dict(sys.modules, {
            "groq": mock_groq,
            "sentence_transformers": mock_st_module,
        }):
            from app.ai import provider as provider_mod
            provider_mod._SENTENCE_TRANSFORMER_CACHE.clear()
            p = self._provider(mock_groq)
            p.embed(["a"])
            p.embed(["b"])
        self.assertEqual(mock_st_module.SentenceTransformer.call_count, 1)


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
