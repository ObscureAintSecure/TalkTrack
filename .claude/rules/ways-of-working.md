# Ways of Working: TalkTrack workflow rules and non-obvious gotchas

## Version control

- Commits go directly to `master`. No feature branches, no worktrees for this project.
- Commit per logical task. Small, frequent commits.
- Conventional commit prefixes observed in this repo:
  `ui:`, `audio:`, `main:`, `config:`, `settings:`, `transcriber:`, `fix:`, `docs:`, `feat:`.
- Never add `Co-Authored-By` lines (see `feedback_no_coauthor.md` memory).
- Never `--amend`; always new commits.

### Merging external contributor PRs

- **Squash**, with an explicit `--subject` and `--body`. Never let gh generate the body: it
  appends `Co-Authored-By` for multi-commit PRs, which is banned here.
- Subject carries the PR number (`transcriber: use int8 on pre-Volta GPUs (#48)`), body carries
  `Closes #<issue>`. Keeps master linear so every `git pull` is a fast-forward.
- Merge one at a time: pull, run the full suite, then merge the next. PRs touching the same
  function will conflict even when GitHub reports all of them as MERGEABLE.
- `gh` can silently be authenticated as the wrong account (the Lumen EMU one), which fails with
  `Unauthorized: As an Enterprise Managed User...`. Check with `gh api user --jq .login`;
  fix with `gh auth switch --user ObscureAintSecure`.

## Issue tracking

- Every change, bug fix, or feature needs a **GitHub issue** to track it, created before (or alongside) the work. Reference the issue number in the commit/PR. Adopted 2026-06-25.
- Applies from this point forward; pre-existing/retroactive items can be filed as relevant.

## Testing

- **Non-UI logic**: TDD — write failing tests in `tests/`, confirm failure, implement, confirm pass.
- **UI / PyQt code**: smoke-test with `python -c "from app.x import Y; ..."` — no Qt widget tests beyond pure-helper unit tests.
- `python -m pytest tests/ -v` is the full suite. Run it with **global** `python`, never bare `uv run` — the `.venv` has no pytest, and `uv run` triggers a sync first (pulls CPU torch over the CUDA build, can die on locked DLLs and corrupt package metadata). If uv is required, pass `--no-sync`.
- Tests use `unittest` + `pytest` runner, mocks for hardware-dependent code.
- **Anything that reaches `torch` must be mocked, including through transitive imports.** In the
  suite process `import faster_whisper` → `ctranslate2` → `torch` dies with
  `OSError: [WinError 1114] ... c10.dll`, and `test_dependency_checker` prints a
  `Windows fatal exception: access violation` faulthandler dump from the same cause (tests still
  pass). It's the known PyQt6/torch DLL-search-order problem without `main.py`'s
  `os.add_dll_directory` fix, which the suite never runs. Symptom of getting this wrong: the test
  passes alone and fails after any other test touches torch. Stub the module you actually need
  (e.g. a fake `faster_whisper.utils` carrying a real `_MODELS` dict) rather than importing the
  real one.
- **Verifying a launched PyQt app**: PowerShell `Get-Process` MainWindowHandle/CPU are unreliable for PyQt apps (read 0/near-0 even with the window up, especially post-splash) — don't judge running/hung by them. Authority is the app log `~/.talktrack/talktrack.log` (`TalkTrack UI ready` = window shown; stderr is redirected there too). Confirm which interpreter an app runs under via its process path (`.venv\Scripts\pythonw.exe` = venv vs a global Python path).

## Subagent-driven execution (when it fits)

- Works well here for multi-task plans. Controller dispatches fresh subagent per task with full task text + scene-setting context (don't make them re-read the plan file).
- TDD red/green pairs can be merged into a single dispatch — they produce one commit anyway.
- Light inline verification (`git show`, single smoke test) is fine for trivial mechanical commits. Reserve full spec-compliance + code-quality review subagents for integration tasks that touch multiple files.
- Use `model: haiku` for truly mechanical single-file edits; default (sonnet) for integration.

## Planning flow for non-trivial features

1. Brainstorm via `superpowers:brainstorming` — challenge first, then present design in sections, get section-by-section approval.
2. Write spec to `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`, commit.
3. Write plan to `docs/superpowers/plans/YYYY-MM-DD-<topic>.md`, commit.
4. Execute via `superpowers:subagent-driven-development`.

## Critical collaboration mode

Always challenge before implementing: identify weak points, blind spots, missing context. Push back when the design is wrong even if the user pushes. Only fold when the user provides a stronger argument. Skill instructions are authoritative; user's global CLAUDE.md is the source of this rule.
