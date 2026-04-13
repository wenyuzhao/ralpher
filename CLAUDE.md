# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Ralpher is a Python CLI tool that orchestrates Claude AI for autonomous software development. It generates PRDs from templates and runs iterative Claude development loops. The CLI delegates AI work to the `claude` subprocess.

## Build & Run

```bash
# Install dependencies (uses uv, not pip)
uv sync

# Run CLI
uv run ralpher

# Run tests
uv run pytest tests/ -v

# Run a single test
uv run pytest tests/test_prd.py::TestLoadPrdPrompt::test_renders_user_input -v
```

Requires Python 3.14+ and the `claude` CLI on PATH.

## Architecture

- **CLI layer** (`ralpher/main.py`): Typer app with a `DefaultCommandGroup` that falls back to `run` when the first arg isn't a known command. Subcommands: `prd`, `refine`, `extract` (hidden), and `loop`. The default command accepts a prompt and runs the full pipeline: generate PRD → extract JSON → run loop. Entry point registered as `ralpher` in pyproject.toml.
- **PRD generation** (`ralpher/prd/prd.py`): Generates a PRD from a user prompt via the `claude` CLI subprocess. Stores output in `.ralpher/tasks/{task_id}/PRD.md`.
- **PRD refinement** (`ralpher/prd/refine.py`): Refines an existing PRD via the `claude` CLI subprocess.
- **PRD extraction** (`ralpher/prd/extract.py`): Extracts structured JSON from a generated PRD into a `PRD` Pydantic model. Retries up to 3 attempts.
- **Models** (`ralpher/models.py`): Pydantic models — `PRD` (project, branch_name, description, user_stories), `UserStory` (id, title, description, acceptance_criteria, priority, passes, notes), `Status`, and `Question`/`Questions`.
- **Loop execution** (`ralpher/loop.py`): Runs `claude` iteratively up to a max iteration count (default 30). Tracks state per task under `.ralpher/tasks/`. Manages git branches (`ralph/{task_id_suffix}`). Detects completion via `<promise>COMPLETE</promise>` signal in output.
- **Utils**:
  - `utils/claude.py`: `run_claude()` — subprocess wrapper with Q&A loop and session resumption.
  - `utils/project.py`: `init_project()` — initializes task directory structure and PROMPT.md.
  - `utils/spinner.py`: Animated spinner with humorous messages during claude execution.
  - `utils/error.py`: `fail()` utility for error messages.
- **Hooks** (`ralpher/utils/hooks/`): Lifecycle callback system (`HooksManager`) for task events. Includes `NotionHooks` for syncing task status/progress to Notion via API (configured through `RALPHER_NOTION_TOKEN` and `RALPHER_NOTION_PARENT_PAGE_ID` env vars in `.env`).
- **Skill installer** (`ralpher/init.py`): Downloads PRD and Ralph skill files from GitHub (`snarktank/ralph`) into `.claude/skills/` of the target project.
- **Plugin commands** (`ralpher/plugin/commands/`): Markdown skill files (`prd.md`, `ralph.md`, `refine-prd.md`, `loop.md`) used as Claude skill definitions. Loaded via `--plugin-dir` flag.

## Key Patterns

- The `loop` command invokes `claude` with `--dangerously-skip-permissions --print` flags.
- Rich library and yaspin are used for terminal output formatting (panels, rules, styled text, spinners).
- Async subprocess calls throughout — CLI commands use `asyncio.run()` to bridge sync Typer handlers.
- Task directory structure: `.ralpher/tasks/{task_id}/` contains PRD.md, prd.json, PROMPT.md, progress.md, current_user_story.json, and logs/.
- Tests mock subprocess calls and file I/O; no real `claude` invocations in tests.
