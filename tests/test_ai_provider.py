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


if __name__ == "__main__":
    unittest.main()
