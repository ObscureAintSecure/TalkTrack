# Packaging and launch: uv venv, CPU/CUDA torch, taskbar icon

## Install model (uv-first, isolated `.venv`)

- `start.bat` is uv-first: `uv sync` into a project-local `.venv`, falling back to a pip-created `.venv` when uv isn't on PATH. It never installs into global Python. `start_debug.bat` = same env, console mode (`python`, not `pythonw`) for log output.
- Plain-pip path: `requirements.txt`, kept in sync with `pyproject.toml`.
- `pyproject.toml` has `package = false` (runnable app, not an importable library).

## CPU vs CUDA torch

- torch/torchaudio are **not** in base dependencies. They're split into mutually-exclusive `cpu` and `cuda` extras (`[tool.uv] conflicts`) sourced from explicit PyTorch indexes (`pytorch-cpu`, `pytorch-cu126`).
- Bare `uv sync` (no extra) still resolves CPU torch transitively, so CPU-only users are unaffected and `start.bat` needs no extra.
- GPU: `uv sync --extra cuda` (or `pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu126`). cu126 matches the suggestion in `dependency_checker.py`.
- Verify resolutions with `uv export --extra cpu` / `--extra cuda` (CPU build = `+cpu`, GPU = `+cu126`).

## Dependency version caps

- Heavy ML deps (numpy, scipy, torch, torchaudio, transformers, pyannote-audio, sentence-transformers, faster-whisper) carry `<next-major` upper bounds in `pyproject.toml` + `requirements.txt`, so a future `uv lock` or plain-pip install can't silently pull an untested major (e.g. numpy 1→2, transformers 4→5).
- After any dep change: regenerate `uv lock` and confirm it still resolves (`uv lock --check`) + suite green.

## Taskbar icon = venv-targeted Start Menu shortcut (no exe)

- `TalkTrack.exe` and `build.py` were **removed**. The custom taskbar icon now comes from a Start Menu shortcut created by `app/utils/start_menu.py`, targeting `.venv\Scripts\pythonw.exe` + `talktrack.ico` + AppUserModelID `TalkTrack.TalkTrack.1`. `main.py` sets the matching per-window AppUserModelID so Windows resolves the shortcut's icon onto the taskbar.
- Offered once on first run (`general.start_menu_offer_done` config flag) and any time via Help > Add to Start Menu.
- A real venv `pythonw.exe` works as a shortcut target; the MS Store `pythonw` *alias* does not — that was the exe's original reason for existing, now moot under the venv.
- Cannot programmatically pin to the taskbar (Windows blocks self-pinning); the user drags/pins manually.

## uv-on-Windows gotcha

- `uv sync --extra cuda` can fail with `failed to rename ... Access is denied (os error 5)` — antivirus (Defender) locking the ~2.4GB torch wheel in uv's cache during extraction. Retry, `uv cache clean`, exclude `%LOCALAPPDATA%\uv\cache`, or use the pip cu126 path. (issue #5)
- An **interrupted** `uv sync` can gut a package's dist-info while leaving it importable: `importlib.metadata.version()` returns None and the app fails transcription with "Unable to compare versions … found=None" (raised in transformers via the faster-whisper import chain). Repair: close the app, `uv pip install --python .venv\Scripts\python.exe --force-reinstall <pkg>` — touches only that package. The System Status panel detects this (`check_package_metadata`, #41).

## CI (#12, #83)

`.github/workflows/ci.yml`, on push to master and on every PR. Two jobs, both windows-latest:

- **test** — installs via `pip install -r requirements.txt` deliberately, not uv, so CI exercises
  what a user without uv actually runs. Then an import smoke (catches import-time breakage like
  the torch/PyQt6 DLL ordering problem, which no unit test would reach) and the full suite.
- **uv-lock** — `uv lock --check`, since the torch extras resolve from explicit indexes and the
  lock can drift from `pyproject.toml`.

`cancel-in-progress` is scoped to pull requests only. Applying it to master cancelled superseded
runs and let a commit land on the default branch unverified (happened once, to 9630438).

`astral-sh/setup-uv` publishes **no moving major tag** — `@v10` does not resolve, so it is pinned
exactly and needs manual bumps. `actions/checkout` and `actions/setup-python` do publish them.
