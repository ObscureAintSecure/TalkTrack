# AI Providers: config keys, context limits, timeouts, embed cache

Conventions from issues #13, #15, #30, #31, #33, #36.

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
- Search runs in `recordings_list._SearchWorker` (QThread, latest-query-wins).
- **Per-recording embedding cache (#33)**: each recording dir gets `embeddings.npz` mapping sha1(segment text) → vector, keyed by `provider.embed_model_id`. `embedding_cache.get_corpus_vectors` embeds only cache misses and prunes stale hashes — transcript edits invalidate per segment automatically. Every provider must set `embed_model_id` (base default None = caching disabled); it MUST change whenever `embed()`'s vectors would (`st:<sentence-transformer name>` / `openai:<api model>` convention). A model-id mismatch or corrupt npz drops the whole file for that recording — never mix vectors across models.

## Model IDs go stale — check the vendor's deprecation page, not its model list

Shipped model IDs rot. Groq's `/docs/models` page still listed
`llama-3.3-70b-versatile` and `llama-3.1-8b-instant` as *production* well after
`/docs/deprecations` recorded their 2026-08-16 shutdown for free/developer tier.
Trusting the model list alone shipped a default that 404s on the first call
(`model_not_found`) — auth and endpoint are fine, so it reads as a key problem.

- When adding or refreshing a provider's list, read the **deprecation page too**.
- Pin the default in a test. `test_ai_provider.DECOMMISSIONED_GROQ_MODELS` +
  `test_default_model_is_a_live_groq_model` / `test_factory_default_is_a_live_groq_model`
  exist because the provider default and the `provider_factory` default are written
  in two places and only the factory one is used when a config omits `model`.
- `settings_dialog.ai_model` is `setEditable(True)` for every provider, so a user
  can always type a newer ID — the curated list is a convenience, not a constraint.

## Error surfacing

- Summarize errors go through `_on_summarize_error` → panels' `set_error()` (restores prior content when it exists). Never leave panels in `set_loading` state on failure.
- Settings "Test Connection" calls `provider.complete()` directly so the real auth/model exception reaches the dialog — `AIProvider.test_connection()` swallows exceptions and is only suitable for boolean checks.
