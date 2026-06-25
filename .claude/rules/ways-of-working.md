# Ways of Working: TalkTrack workflow rules and non-obvious gotchas

## Version control

- Commits go directly to `master`. No feature branches, no worktrees for this project.
- Commit per logical task. Small, frequent commits.
- Conventional commit prefixes observed in this repo:
  `ui:`, `audio:`, `main:`, `config:`, `settings:`, `transcriber:`, `fix:`, `docs:`, `feat:`.
- Never add `Co-Authored-By` lines (see `feedback_no_coauthor.md` memory).
- Never `--amend`; always new commits.

## Issue tracking

- Every change, bug fix, or feature needs a **GitHub issue** to track it, created before (or alongside) the work. Reference the issue number in the commit/PR. Adopted 2026-06-25.
- Applies from this point forward; pre-existing/retroactive items can be filed as relevant.

## Testing

- **Non-UI logic**: TDD — write failing tests in `tests/`, confirm failure, implement, confirm pass.
- **UI / PyQt code**: smoke-test with `python -c "from app.x import Y; ..."` — no Qt widget tests beyond pure-helper unit tests.
- `python -m pytest tests/ -v` is the full suite.
- Tests use `unittest` + `pytest` runner, mocks for hardware-dependent code.

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
