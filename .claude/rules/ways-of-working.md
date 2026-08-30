# Ways of Working: TalkTrack workflow rules and non-obvious gotchas

## GitHub account

**This repo is always the personal account `ObscureAintSecure`.** Two accounts sit in the `gh`
keyring and the active one can flip between sessions. Check before anything that writes — issues,
comments, PR merges:

```
gh api user --jq .login                       # expect ObscureAintSecure
gh auth switch --user ObscureAintSecure       # if it says Buddy-Bergman_Lumen
```

The work account is an Enterprise Managed User and cannot write to this repo at all. Two different
symptoms, same cause:

- API writes: `GraphQL: Unauthorized: As an Enterprise Managed User, you cannot access this content`
- `git push`: `remote: Permission to ObscureAintSecure/TalkTrack.git denied to Buddy-Bergman_Lumen`
  (403) — the credential helper follows the active `gh` account

Neither error names the real problem, so both read as permissions bugs. The active account flips
back to the work one on its own, more than once per session — re-check it every time rather than
trusting an earlier switch. A read-only `gh` call proves nothing; check `gh api user` specifically.

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
- **First-time contributors get no CI until you approve it.** Their runs sit as
  `action_required`, so the PR shows no checks at all. Find them with
  `gh api repos/ObscureAintSecure/TalkTrack/actions/runs --jq '.workflow_runs[] | select(.status=="action_required")'`
  and approve with `gh api -X POST .../actions/runs/<id>/approve`.

### Taking over a stale PR

When a contributor goes quiet and their branch is conflicting, adopt it rather than closing it:

1. `git fetch origin pull/N/head:prN`
2. Check the real conflict scope first: `git merge-tree --write-tree --name-only HEAD prN`
   (usually far smaller than GitHub's CONFLICTING badge implies)
3. `git cherry-pick <their commits>` — preserves their authorship and adds no `Co-Authored-By`
4. Put your own change in a **separate** commit on top, so the history shows who decided what
5. Close the PR with a comment crediting them and explaining exactly what you changed

## Issue tracking

- Every change, bug fix, or feature needs a **GitHub issue** to track it, created before (or alongside) the work. Reference the issue number in the commit/PR. Adopted 2026-06-25.
- Applies from this point forward; pre-existing/retroactive items can be filed as relevant.

## Testing

- **Non-UI logic**: TDD — write failing tests in `tests/`, confirm failure, implement, confirm pass.
- **UI / PyQt code**: smoke-test with `python -c "from app.x import Y; ..."`. Constructing real
  widgets in tests is still out, but a UI *method* can be tested without Qt by calling it
  against a stub self: `MainWindow._start_system_monitor(stub)`, `DiarizationWorker.run(stub)`
  where `stub = MagicMock()` carrying the attributes the method touches. Patch collaborators
  with `autospec=True` so a signature mismatch raises instead of being absorbed by a
  permissive mock. #79 (Test Mic dead for ~7 weeks on a removed kwarg) survived precisely
  because that path had no cover.
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

## Editing files from Bash

Bash heredocs mangle backslash escapes. Writing a Python string literal that should contain
a literal backslash-n through `<<'EOF'` yields a real newline instead, silently breaking the
literal (cost one broken `settings_dialog.py` and a `git checkout` to recover). For content
with escapes, build the string with `chr(92)` or replace by line index, then confirm with
`python -c "import ast; ast.parse(open(path).read())"` before moving on.
