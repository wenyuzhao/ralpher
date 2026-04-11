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

- **CLI layer** (`ralpher/main.py`): Typer app with `init` and `loop` subcommands. Entry point registered as `ralpher` in pyproject.toml.
- **PRD generation** (`ralpher/prd.py`): Loads Jinja2 template from `ralpher/prompts/prd.md`, strips YAML frontmatter, renders with user input, then passes to `claude` CLI via subprocess.
- **Loop execution** (`ralpher/loop.py`): Runs `claude` iteratively up to a max iteration count. Tracks state in `progress.txt` and `prd.json` at the working directory. Detects completion via `<promise>COMPLETE</promise>` signal in output. Archives state when the git branch changes.
- **Skill installer** (`ralpher/init.py`): Downloads PRD and Ralph skill files from GitHub (`snarktank/ralph`) into `.claude/skills/` of the target project.

## Key Patterns

- Jinja2 templates use `StrictUndefined` — all variables must be provided or rendering fails.
- The `loop` command invokes `claude` with `--dangerously-skip-permissions --print` flags.
- Rich library is used for all terminal output formatting (panels, rules, styled text).
- Tests mock subprocess calls and file I/O; no real `claude` invocations in tests.
