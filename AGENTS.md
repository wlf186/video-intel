# Repository Guidelines

## Project Structure & Module Organization

Sandevistan Video runs local MiniMax H3 video/audio generation through ComfyUI.

- `video_intel/`: FastAPI endpoints (`app.py`), job execution (`service.py`), prompt assembly, workflows, storage, and process supervision.
- `frontend/src/`: React/TypeScript pages and components; shared styles live in `styles.css`. Images live in `frontend/public/`; offline API documentation assets live in `static/swagger/`.
- `tests/`: pytest suites for jobs, prompts, API behavior, and storage.
- `scripts/`: setup, model downloads, service helpers, and real-generation verification.
- `data/`, `models/`, `cache/`, `logs/`, `run/`, and `tmp/`: local runtime artifacts, excluded from Git. `vendor/` contains ComfyUI.

## Build, Test, and Development Commands

Run commands from the repository root.

- `./scripts/setup.sh`: install dependencies, download approximately 64 GB of models, and build the frontend. Requires uv, ffmpeg, npm, and Node.js 22.12+; provisions Python 3.12.
- `./service.sh start`: launch the supervised API and inference backend. Use `status`, `logs`, `restart`, or `stop` for lifecycle operations. The app serves on port 20820.
- `npm --prefix frontend ci`: install locked frontend dependencies.
- `npm --prefix frontend run dev`: start the Vite development server.
- `npm --prefix frontend run build`: type-check and create the production bundle.
- `.venv/bin/python -m pytest tests -q`: run backend tests.
- `.venv/bin/ruff check video_intel tests scripts`: lint Python code.

## Coding Style & Naming Conventions

Follow existing formatting: four-space Python indentation; two-space TypeScript indentation, double quotes, and semicolons. Use `snake_case` for Python functions/modules, `PascalCase` for React components and component filenames, and `camelCase` for TypeScript functions/variables. TypeScript uses strict checking. Prettier is available in frontend dependencies. Preserve bilingual interface strings.

## Testing Guidelines

Name pytest files `test_*.py` and functions `test_*`. Use `tmp_path`, monkeypatching, and mocked backend calls to isolate databases and files. Add regression coverage for changed behavior; no numeric coverage threshold is configured. For UI changes, check desktop/mobile layouts and both languages. Scripts named `verify_generation.py` and `verify_production.py` perform separate, GPU-intensive acceptance checks.

## Commit & Pull Request Guidelines

This checkout lacks Git history, so no established commit convention can be verified. Use concise imperative subjects. PRs should explain behavior changes, link relevant issues, report validation commands/results, and include screenshots for UI changes.

## Security & Configuration

The service has no authentication; keep deployment within trusted networks. Configure listening addresses through `VIDEO_INTEL_HOST`, `VIDEO_INTEL_PORT`, and `VIDEO_INTEL_BACKEND_PORT`. Keep model weights, generated media, databases, and environments out of commits.
