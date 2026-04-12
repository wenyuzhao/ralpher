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

- **CLI layer** (`ralpher/main.py`): Typer app with `init`, `prd`, `extract`, and `loop` subcommands. The default command (no subcommand) accepts a prompt and runs the full pipeline: generate PRD → extract JSON → run loop. Entry point registered as `ralpher` in pyproject.toml.
- **PRD generation** (`ralpher/prd/prd.py`): Generates a PRD from a user prompt via the `claude` CLI subprocess. Stores output in `.ralpher/tasks/{task_id}/PRD.md`.
- **PRD extraction** (`ralpher/prd/extract.py`): Extracts structured JSON from a generated PRD into a `PRD` Pydantic model.
- **Models** (`ralpher/models.py`): Pydantic models — `PRD` (project, branch_name, description, user_stories) and `UserStory` (id, title, description, acceptance_criteria, priority, passes, notes).
- **Loop execution** (`ralpher/loop.py`): Runs `claude` iteratively up to a max iteration count. Tracks state per task under `.ralpher/tasks/`. Detects completion via `<promise>COMPLETE</promise>` signal in output.
- **Skill installer** (`ralpher/init.py`): Downloads PRD and Ralph skill files from GitHub (`snarktank/ralph`) into `.claude/skills/` of the target project.
- **Plugin commands** (`ralpher/plugin/commands/`): Markdown skill files (`prd.md`, `ralph.md`, `loop.md`) used as Claude skill definitions.

## Key Patterns

- The `loop` command invokes `claude` with `--dangerously-skip-permissions --print` flags.
- Rich library is used for all terminal output formatting (panels, rules, styled text).
- Async subprocess calls throughout — CLI commands use `asyncio.run()` to bridge sync Typer handlers.
- Tests mock subprocess calls and file I/O; no real `claude` invocations in tests.
