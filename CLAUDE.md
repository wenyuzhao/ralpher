# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Ralpher is a Python CLI tool that orchestrates the `claude` CLI for autonomous software development. It generates a Project Plan from a user prompt, extracts it into structured tasks, then runs an iterative Ralph-loop where Claude implements one task at a time on a dedicated git branch. All AI work is delegated to the `claude` subprocess — there's no direct API integration.

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

Requires Python 3.14+ and the `claude` CLI on PATH (checked at startup by `_require_claude`).

## Linting & Formatting

```bash
uvx ruff check .          # lint
uvx ruff check --fix .    # lint + autofix
uvx ruff format .         # format
```

## Architecture

### CLI layer — [ralpher/main.py](ralpher/main.py)
Typer app with a `DefaultCommandGroup` that routes unknown first args to a `run` default command. Subcommands: `plan`, `refine`, `extract` (hidden), `loop`. Entry point `ralpher` → `ralpher.main:main`. All handlers are sync Typer callbacks that bridge to async via `asyncio.run()`.

### Project state — [ralpher/models.py](ralpher/models.py)
The `Project` Pydantic model is the central handle for a run. It owns all filesystem paths under `.ralpher/projects/{project_id}/` via properties (`plan_md`, `tasks_json`, `progress_md`, `prompt_md`, `questions_json`, `current_task_json`, `config_json`) and load/save helpers for `Tasks`, `Questions`, `ProjectConfig`, and `current_task`. `Task` has `id`, `title`, `description`, `acceptance_criteria`, and a `passes` boolean — the loop picks the first failing task each iteration. `ProjectConfig` stores `base_branch` and `target_branch` for the run.

### Plan flow — [ralpher/plan/](ralpher/plan/)
- [plan.py](ralpher/plan/plan.py) initializes the project directory + git branches, then invokes `claude` with `/ralpher:plan` via `run_claude_plan_mode` (Q&A loop — Claude can return either a finished plan or clarification questions, which are prompted to the user interactively).
- [refine.py](ralpher/plan/refine.py) runs `/ralpher:refine` against an existing plan.
- [extract.py](ralpher/plan/extract.py) parses `PLAN.md` into structured `Tasks` JSON via Claude with a JSON schema; retries up to 3 attempts.

### Loop execution — [ralpher/loop/](ralpher/loop/)
- [loop.py](ralpher/loop/loop.py) `run_ralph_loop` is the main driver: calls `prepare`, then iterates until `max_iterations` (default 30) or all tasks pass. Each iteration picks the first failing task, invokes `iterate`, and reloads `tasks.json` to check progress.
- [iterate.py](ralpher/loop/iterate.py) writes `current_task.json`, calls Claude with `/ralpher:iterate` and a `Result { task_passed }` schema, then updates `tasks.json`.
- [prepare.py](ralpher/loop/prepare.py) handles first-run setup (extracting tasks, initializing progress).

### Claude subprocess — [ralpher/utils/claude.py](ralpher/utils/claude.py)
`run_claude` and `run_claude_plan_mode` are the only ways to invoke `claude`. Key flags passed:
- `--permission-mode dontAsk`, `--output-format stream-json`, `--verbose`
- `--plugin-dir <ralpher/plugin>` so the `/ralpher:*` slash commands resolve
- `--json-schema <pydantic schema>` for structured output (Claude writes a `result` JSONL record with a `structured_output` field, which `_load_structured_output` parses from the log)
- `--dangerously-skip-permissions` unless `readonly=True` (in which case `READONLY_TOOLS` is used)
- `--resume <session_id>` for Q&A continuation in plan mode

All subprocess output is tee'd to `.ralpher/projects/{project_id}/logs/claude-{timestamp}.log`, and `session_id` is recovered by scanning that log.

### Plugin — [ralpher/plugin/](ralpher/plugin/)
`skills/{plan,iterate,refine,extract-tasks}/SKILL.md` — Claude skill definitions loaded via `--plugin-dir`. These are the actual prompts that drive Claude; most behavior lives in markdown, not Python. Adapted from [snarktank/ralph](https://github.com/snarktank/ralph).

### Git branch management — [ralpher/utils/git.py](ralpher/utils/git.py)
Each project runs on `ralph/{project_id}`, forked from a resolved base branch (`--base-branch`, else `main`, else `master`). `checkout_branch` auto-inits the repo with an empty commit if none exists. A `.no-branch` sentinel file in the repo root disables automatic branch creation (useful for repos that should stay on a single branch).

### Hooks — [ralpher/utils/hooks/](ralpher/utils/hooks/)
`HooksManager` dispatches lifecycle callbacks (`on_loop_start`, `on_iteration_start/end`, `on_error`, `on_loop_end`) to registered hooks. `NotionHooks` syncs task status/progress to a Notion page — configured via `RALPHER_NOTION_TOKEN` and `RALPHER_NOTION_PARENT_PAGE_ID` in `.env` (loaded by `load_dotenv` in the `loop` command).

## Key Patterns

- **Structured output over text parsing.** Anywhere Claude needs to return data, pass a Pydantic model as `schema=` to `run_claude` — the framework serializes `model_json_schema()` into `--json-schema` and validates the returned `structured_output`. Avoid regex/markdown parsing of stdout.
- **Project is the bag of paths.** Don't hardcode paths under `.ralpher/projects/...`; go through `Project` properties so layout changes stay local to [models.py](ralpher/models.py).
- **Tests mock subprocess + filesystem.** No real `claude` invocations in [tests/](tests/). When adding loop/plan behavior, patch `run_claude` / `run_claude_plan_mode` and assert on the prompt + schema arguments.
- **Async all the way down.** Every Claude-touching function is `async`; CLI handlers use `asyncio.run()` as the single bridge. Don't introduce blocking `subprocess.run` for Claude — only the thin git helpers are sync.
- **Rich + yaspin for UX.** Progress is shown via `rich.print` and `Spinner` (wraps the subprocess with humorous status messages). Raw Claude stdout/stderr goes to the log file, not the terminal.
