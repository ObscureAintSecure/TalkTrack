# AI Providers: config keys, context limits, timeouts, embed cache

Conventions from issues #13, #15, #30, #31, #36.

## Config keys

- Local provider model path lives in `config["ai"]["local_model_path"]` — the `model` key holds the settings-combo placeholder `"(set path below)"` for local. `provider_factory` reads `local_model_path` first (#13); keep that precedence.
- Per-provider API keys/models live in `provider_settings` keyed by provider name.

## Context limits

- `AIProvider.max_context_chars` (class attr): 100k default (cloud), `LocalProvider` overrides to 8k (n_ctx=4096 tokens + instruction/completion headroom).
- Summary/action-item prompt builders take `max_transcript_chars`; pass `provider.max_context_chars`. Truncation keeps head AND tail (60/40) with a marker — action items cluster late in meetings, so a chat-style head-only cut drops exactly what the prompt needs.
- Chat has its own separate 12k char cap (`chat.MAX_CONTEXT_CHARS`).

## Request timeouts (120s convention, #36)

- Anthropic / OpenAI / Grok: `timeout=120.0` constructor kwarg.
- Gemini (`google.generativeai`): per-call `request_options={"timeout": 120.0}` on `generate_content` — no client-level kwarg.
- Mistral: NO timeout kwarg in the SDK — pass `client=httpx.Client(timeout=120.0)` to the constructor.
- New providers must set an explicit timeout; SDK defaults (~10 min) hang the worker and block app close.

## Embeddings

- All local-embedding providers use `provider.get_sentence_transformer(name)` (module-level cache). Never instantiate `SentenceTransformer` directly — per-call construction cost seconds and re-downloaded on first use (#31).
- Search runs in `recordings_list._SearchWorker` (QThread, latest-query-wins). Corpus embeddings are still recomputed per search — persistence is open issue #33.

## Error surfacing

- Summarize errors go through `_on_summarize_error` → panels' `set_error()` (restores prior content when it exists). Never leave panels in `set_loading` state on failure.
- Settings "Test Connection" calls `provider.complete()` directly so the real auth/model exception reaches the dialog — `AIProvider.test_connection()` swallows exceptions and is only suitable for boolean checks.
