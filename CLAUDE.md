# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Ralpher is a Python CLI tool that orchestrates Claude AI for autonomous software development. It generates Project Plans from templates and runs iterative Claude development loops. The CLI delegates AI work to the `claude` subprocess.

## Build & Run

```bash
# Install dependencies (uses uv, not pip)
uv sync

# Run CLI
uv run ralpher

# Run tests
uv run pytest tests/ -v

# Run a single test
uv run pytest tests/test_plan.py::TestGeneratePlan::test_returns_task_id_on_success -v
```

Requires Python 3.14+ and the `claude` CLI on PATH.

## Linting & Formatting

This project uses **ruff** for linting and formatting.

```bash
# Lint
uvx ruff check .

# Lint and auto-fix
uvx ruff check --fix .

# Format
uvx ruff format .
```

## Architecture

- **CLI layer** (`ralpher/main.py`): Typer app with a `DefaultCommandGroup` that falls back to `run` when the first arg isn't a known command. Subcommands: `plan`, `refine`, `extract` (hidden), and `loop`. The default command accepts a prompt and runs the full pipeline: generate plan → extract JSON → run loop. Entry point registered as `ralpher` in pyproject.toml.
- **Plan generation** (`ralpher/plan/plan.py`): Generates a Project Plan from a user prompt via the `claude` CLI subprocess. Stores output in `.ralpher/projects/{project_id}/PLAN.md`.
- **Plan refinement** (`ralpher/plan/refine.py`): Refines an existing Project Plan via the `claude` CLI subprocess.
- **Plan extraction** (`ralpher/plan/extract.py`): Extracts structured JSON from a generated Project Plan into a `ProjectPlan` Pydantic model. Retries up to 3 attempts.
- **Models** (`ralpher/models.py`): Pydantic models — `Project` (id, model, max_iterations, and project directory/file accessors), `ProjectPlan` (project, description, tasks), `Task` (id, title, description, acceptance_criteria, priority, passes, notes), `Status`, and `Question`/`Questions`.
- **Loop execution** (`ralpher/loop/`): Runs `claude` iteratively up to an optional max iteration count (unlimited by default). Tracks state per project under `.ralpher/projects/`. Manages git branches (`ralph/{project_id_suffix}`).
- **Utils**:
  - `utils/claude.py`: `run_claude()` — subprocess wrapper with Q&A loop and session resumption.
  - `utils/project.py`: `init_project()` — initializes project directory structure and PROMPT.md.
  - `utils/spinner.py`: Animated spinner with humorous messages during claude execution.
  - `utils/error.py`: `fail()` utility for error messages.
- **Hooks** (`ralpher/utils/hooks/`): Lifecycle callback system (`HooksManager`) for project events. Includes `NotionHooks` for syncing task status/progress to Notion via API (configured through `RALPHER_NOTION_TOKEN` and `RALPHER_NOTION_PARENT_PAGE_ID` env vars in `.env`).
- **Skill installer** (`ralpher/init.py`): Downloads plan and Ralph skill files from GitHub (`snarktank/ralph`) into `.claude/skills/` of the target project.
- **Plugin commands** (`ralpher/plugin/commands/`): Markdown skill files (`plan.md`, `iterate.md`, `refine-plan.md`, `extract-plan.md`) used as Claude skill definitions. Loaded via `--plugin-dir` flag.

## Key Patterns

- The `loop` command invokes `claude` with `--dangerously-skip-permissions --print` flags.
- Rich library and yaspin are used for terminal output formatting (panels, rules, styled text, spinners).
- Async subprocess calls throughout — CLI commands use `asyncio.run()` to bridge sync Typer handlers.
- Project directory structure: `.ralpher/projects/{project_id}/` contains PLAN.md, plan.json, PROMPT.md, progress.md, current_task.json, and logs/.
- The `Project` model centralizes all file path properties (`project_dir`, `plan_md`, `plan_json`, `progress_md`, `prompt_md`, `questions_json`, `current_task_json`) and load/save methods.
- Tests mock subprocess calls and file I/O; no real `claude` invocations in tests.
