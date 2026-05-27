# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Ralpher is a Python CLI tool that orchestrates a coding agent for autonomous software development. It generates a Project Plan from a user prompt, extracts it into structured tasks, then runs an iterative Ralph-loop where the agent implements one task at a time on a dedicated git branch. All AI work is delegated to an agent backend — either Claude Code (the `claude` CLI, via the Claude Agent SDK) or the Google Antigravity SDK (Gemini). There's no direct API integration; the backend is selected per run by the `--backend` flag (else the `backend` key in `.ralpher/settings.json`) — see the Backends section under Architecture.

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

Requires Python 3.14+. Each command checks the selected backend's prerequisites at startup via `_require_agent`: the `claude` CLI on PATH for `claude-code`, or `GEMINI_API_KEY`/`GOOGLE_API_KEY` in the environment for `antigravity`.

## Linting & Formatting

```bash
uvx ruff check .          # lint
uvx ruff check --fix .    # lint + autofix
uvx ruff format .         # format
```

## Architecture

### CLI layer — [ralpher/main.py](ralpher/main.py)
Typer app with a `DefaultCommandGroup` that routes unknown first args to a `run` default command. Subcommands: `plan`, `refine`, `extract` (hidden), `loop`. Entry point `ralpher` → `ralpher.main:main`. All handlers are sync Typer callbacks that bridge to async via `asyncio.run()`. Every command takes `--backend` / `-b` (`BackendOption`); each resolves the backend via `_resolve_backend_or_fail` (flag → `resolve_backend` → settings/default), checks its prerequisites with `_require_backend`, and stores the result on `Project.backend`.

### Project state — [ralpher/models.py](ralpher/models.py)
The `Project` Pydantic model is the central handle for a run. It owns all filesystem paths under `.ralpher/projects/{project_id}/` via properties (`plan_md`, `tasks_json`, `progress_md`, `prompt_md`, `questions_json`, `current_task_json`, `config_json`) and load/save helpers for `Tasks`, `Questions`, `ProjectConfig`, and `current_task`. `Task` has `id`, `title`, `description`, `acceptance_criteria`, and a `passes` boolean — the loop picks the first failing task each iteration. `ProjectConfig` stores `base_branch` and `target_branch` for the run. `Project.backend` (a `BackendKind` = `"claude-code" | "antigravity"`) records which backend drives the run. Backend resolution lives here too: `normalize_backend` maps CLI/settings aliases (`cc`, `agy`, …) to the canonical value, `Settings.backend` (alias-normalizing validator) is the per-checkout default, and `resolve_backend(cli)` implements flag-wins-then-settings. `Settings.model_for(kind, backend)` returns the per-kind default model for the given backend (`CLAUDE_DEFAULT_MODELS` for `claude-code`, `ANTIGRAVITY_DEFAULT_MODELS` for `antigravity`); a model pinned in `settings.json` overrides either. For `antigravity` the reasoning effort rides on the model string as a trailing `:<level>` suffix that `split_thinking_level` peels off — so `model_for` returns just the name and `Settings.thinking_for(kind, backend)` returns the level (e.g. plan/refine/loop → `high`, extract-tasks → `medium`; always `None` for `claude-code`). A bare pinned name with no suffix runs at the SDK's own default effort. A model passed explicitly (the backend's `model` arg, e.g. from a CLI flag) is split the same way, so a `:<level>` suffix there also sets the thinking level.

### Plan flow — [ralpher/plan/](ralpher/plan/)
- [plan.py](ralpher/plan/plan.py) initializes the project directory + git branches, then invokes the agent with the rendered `plan` prompt via `run_agent_plan_mode` (Q&A loop — the agent can return either a finished plan or clarification questions, which are prompted to the user interactively).
- [refine.py](ralpher/plan/refine.py) runs the rendered `refine` prompt against an existing plan.
- [extract.py](ralpher/plan/extract.py) parses `PLAN.md` into structured `Tasks` JSON via the agent with a JSON schema; retries up to 3 attempts.

### Loop execution — [ralpher/loop/](ralpher/loop/)
- [loop.py](ralpher/loop/loop.py) `run_ralph_loop` is the main driver: calls `prepare`, then iterates until `max_iterations` (default 30) or all tasks pass. Each iteration picks the first failing task, invokes `iterate`, and reloads `tasks.json` to check progress.
- [iterate.py](ralpher/loop/iterate.py) writes `current_task.json`, calls the agent with the rendered `iterate` prompt, then verifies with the rendered `verify` prompt and a `Result { task_passed }` schema, then updates `tasks.json`.
- [prepare.py](ralpher/loop/prepare.py) handles first-run setup (extracting tasks, initializing progress).

### Prompts — [ralpher/prompts/](ralpher/prompts/)
`render_prompt(name, **vars)` renders a Jinja2 template in [ralpher/prompts/](ralpher/prompts/) (`plan.md`, `refine.md`, `extract-tasks.md`, `iterate.md`, `verify.md`) and returns the result, which callers pass to `run_agent` / `run_agent_plan_mode` as the **initial prompt**. The templates are the actual prompts that drive the agent — most behavior lives in markdown, not Python. They reference the project's files by absolute path (rendered from `Project` properties), and `plan.md`/`refine.md` embed the `plan-structure.md` reference doc inline (its full text is injected as the `plan_structure` Jinja global) rather than asking the agent to read it — so the agent never needs file access outside the run's workspace (which the antigravity backend enforces). The Jinja env uses `StrictUndefined`, so a template variable that a caller forgets to pass raises at render time. Adapted from [snarktank/ralph](https://github.com/snarktank/ralph). (This replaces the former `--plugin-dir`-loaded `/ralpher:*` skills.)

### Backends — [ralpher/backend/](ralpher/backend/)
The single abstraction boundary for invoking a coding agent. Callers import `run_agent` / `run_agent_plan_mode` from the package façade ([__init__.py](ralpher/backend/__init__.py)) and never touch a specific backend; the dispatcher selects one by `project.backend` and imports it lazily so a run only loads the SDK it uses. The two backends are independent of each other — anything shared lives in [common.py](ralpher/backend/common.py) (the `Plan`/`PlanOrQuestions` plan-mode schema and the `ask_user_questions` clarification UX).
- [common.py](ralpher/backend/common.py) — backend-agnostic plan-mode schema + interactive Q&A.
- [claude.py](ralpher/backend/claude.py) — Claude Agent SDK backend (`run_claude` / `run_claude_plan_mode`). See below.
- [antigravity.py](ralpher/backend/antigravity.py) — Google Antigravity SDK backend (`run_antigravity` / `run_antigravity_plan_mode`). Builds a `LocalAgentConfig` with `response_schema` (a pydantic class; `ChatResponse.structured_output()` returns a dict that's validated against it), `workspaces=[cwd]`, and deny **policies** that keep `.ralpher` write-protected (the analogue of Claude's deny rules). Whole-tool restrictions go through `CapabilitiesConfig` instead (which drops the tool from the model's context entirely): `ask_question` is always in `disabled_tools`, and `readonly` swaps to an `enabled_tools` whitelist of the read-only builtins. A `thinking_level` (resolved per kind via `Settings.thinking_for`) is carried on the full `gemini_config` (a `ModelEntry` with a `GenerationConfig`) rather than the `model` shorthand, since the SDK forbids setting both. Plan mode keeps a single `Agent` open across turns (the analogue of `--resume`). The OS Bash sandbox has no antigravity equivalent, so `project.sandbox` is ignored for this backend. Reads `GEMINI_API_KEY`/`GOOGLE_API_KEY` from the env (`google-antigravity` dependency).

### Claude backend — [ralpher/backend/claude.py](ralpher/backend/claude.py)
`run_claude` and `run_claude_plan_mode` invoke `claude` via the Claude Agent SDK. Key flags passed:
- `--permission-mode dontAsk`, `--output-format stream-json`, `--verbose`
- `--json-schema <pydantic schema>` for structured output (Claude writes a `result` JSONL record with a `structured_output` field, which `_load_structured_output` parses from the log)
- `--dangerously-skip-permissions` unless `readonly=True` (in which case `READONLY_TOOLS` is used)
- `--resume <session_id>` for Q&A continuation in plan mode

All subprocess output is tee'd to `.ralpher/projects/{project_id}/logs/claude-{timestamp}.log`, and `session_id` is recovered by scanning that log. The `.ralpher` directory is kept read-only to the `claude` subprocess via `permissions.deny` rules (built by `_readonly_ralpher_settings` and passed as inline `settings` in `_build_options`) — deny rules are a hard block even under `bypassPermissions`, so Claude can read its plan/task/progress files but never write into `.ralpher`. `_build_options` always sets `setting_sources=["user", "project", "local"]` so the run isn't hermetic — the user's `.claude/settings.json` (e.g. a `sandbox.network` allowlist) is loaded and merged.

When `project.sandbox` is true, `_build_options` also passes `sandbox={"enabled": True}`, which runs the Bash tool in an OS sandbox so the `.ralpher` deny rule is enforced against shell writes too (the tool-path deny alone doesn't cover arbitrary Bash). `Project.sandbox` defaults to `False`; only the `loop` command opts a run in — via the `--sandbox/--no-sandbox` flag, which falls back to `Settings.sandbox` (loaded from `.ralpher/settings.json`, default `True`) when neither flag is given. Note the sandbox denies network by default with no allow-all wildcard, so network-dependent tasks need a `sandbox.network` allowlist in `.claude/settings.json`.

### Git branch management — [ralpher/utils/git.py](ralpher/utils/git.py)
Each project runs on `ralph/{project_id}`, forked from a resolved base branch (`--base-branch`, else `main`, else `master`). `checkout_branch` auto-inits the repo with an empty commit if none exists. A `.no-branch` sentinel file in the repo root disables automatic branch creation (useful for repos that should stay on a single branch).

### Hooks — [ralpher/utils/hooks/](ralpher/utils/hooks/)
`HooksManager` dispatches lifecycle callbacks (`on_loop_start`, `on_iteration_start/end`, `on_error`, `on_loop_end`) to registered hooks. `NotionHooks` syncs task status/progress to a Notion page — configured via `RALPHER_NOTION_TOKEN` and `RALPHER_NOTION_PARENT_PAGE_ID` in `.env` (loaded by `load_dotenv` in the `loop` command).

## Key Patterns

- **Structured output over text parsing.** Anywhere the agent needs to return data, pass a Pydantic model as `schema=` to `run_agent` — each backend requests structured output (Claude via `--json-schema`, antigravity via `response_schema`) and the result is validated against the model. Avoid regex/markdown parsing of stdout.
- **Project is the bag of paths.** Don't hardcode paths under `.ralpher/projects/...`; go through `Project` properties (the root comes from `ralpher_root()`) so layout changes stay local to [models.py](ralpher/models.py).
- **Tests mock the agent + filesystem.** No real `claude`/antigravity invocations in [tests/](tests/). When adding loop/plan behavior, patch `run_agent` / `run_agent_plan_mode` (or, for a specific backend, its module's `Agent`/`_run_query`) and assert on the prompt + schema arguments.
- **Async all the way down.** Every agent-touching function is `async`; CLI handlers use `asyncio.run()` as the single bridge. Don't introduce blocking `subprocess.run` for the agent — only the thin git helpers are sync.
- **Rich + yaspin for UX.** Progress is shown via `rich.print` and `Spinner` (wraps the subprocess with humorous status messages). Raw Claude stdout/stderr goes to the log file, not the terminal.
