# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Ralpher is a Python CLI tool that orchestrates a coding agent for autonomous software development. It generates a Project Plan from a user prompt, extracts it into structured tasks, then runs an iterative Ralph-loop where the agent implements one task at a time on a dedicated git branch. All AI work is delegated to an agent backend — either Claude Code (the `claude` CLI) or Google Antigravity (the `agy` CLI). Both are driven as subprocesses; there is no SDK or direct API integration. The backend is selected per run by the `--backend` flag (else the `backend` key in `.ralpher/settings.toml`) — see the Backends section under Architecture.

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

Requires Python 3.14+. Each command checks the selected backend's prerequisites at startup via `check_prerequisites`, which just verifies the backend's executable is on PATH: `claude` for `claude-code`, `agy` for `antigravity`. Both CLIs carry their own auth (`claude auth` / `agy` sign-in); ralpher reads no API keys.

## Linting, Formatting & Type Checking

```bash
uvx ruff check .          # lint
uvx ruff check --fix .    # lint + autofix
uvx ruff format .         # format
uvx ty check .            # type check
```

**Every change must leave `uvx ruff check .`, `uvx ruff format --check .`, `uvx ty check .`, and
`uv run pytest tests/ -v` all clean.** Run them before reporting a task done — a task with lint,
format, type, or test errors is not finished. Notes on keeping them clean:

- **No ruff config.** The repo has no `[tool.ruff]` section, so ruff's own (broad) default rule
  set applies. Don't silence a rule project-wide to make a finding go away; fix the code.
- **Deliberate blind excepts carry a `# noqa`.** `BLE001`/`S110` are suppressed per-site with a
  one-line reason wherever a broad `except Exception` is the point — best-effort JSONL logging
  that must never break a run, optional Notion sync that degrades to "no page", and the funnels
  that turn any agent SDK failure into `fail()`. Match that style rather than adding new bare
  suppressions or narrowing an intentionally broad catch.
- **Timestamps are tz-aware.** `DTZ005` forbids a naked `datetime.now()`. Use
  `datetime.now().astimezone()` — it keeps the local time these log names, project IDs, and
  progress entries are meant to show, while satisfying the rule.
- **Backends are argv builders.** A new flag belongs in the backend's `build_command`, not in
  the shared driver. Anything that isn't backend-specific (model resolution, logging, spawning,
  error funnelling, structured-output validation) lives in [base.py](ralpher/backend/base.py).
- **`typer`, not `click`.** `typer` vendors its own click at `typer._click`, so a `TyperGroup`
  override must annotate its context as `typer._click.core.Context` (imported as `TyperContext`
  in [main.py](ralpher/main.py)); the top-level `click.Context` is a different class and ty
  rejects it as an invalid override.
- **Narrow optionals in tests.** SDK config objects expose unions (`str | ModelTarget | None`,
  `list[...] | None`, `Callable | None`). Bind the attribute to a local and `assert isinstance(...)`
  / `assert ... is not None` before drilling in, so the assertion reads as an assertion and ty can
  follow it.

## Architecture

### CLI layer — [ralpher/main.py](ralpher/main.py)
Typer app with a `DefaultCommandGroup` that routes unknown first args to a `run` default command. Subcommands: `plan`, `refine`, `extract` (hidden), `loop`. Entry point `ralpher` → `ralpher.main:main`. All handlers are sync Typer callbacks that bridge to async via `asyncio.run()`. Every command takes `--backend` / `-b` (`BackendOption`); each resolves the backend via `_resolve_backend_or_fail` (flag → `resolve_backend` → settings/default), checks its prerequisites with `check_prerequisites`, and stores the result on `Project.backend`. `plan`, `refine`, and `loop` additionally take `--jj/--no-jj` (`JjOption`), resolved the same way by `_resolve_jj_or_fail` (flag → `resolve_jj` → settings, then `check_jj_prerequisites`) and stored on `Project.jj`. `extract` has no `--jj` flag because `extract-tasks.md` never mentions version control.

### Project state — [ralpher/models.py](ralpher/models.py)
The `Project` Pydantic model is the central handle for a run. It owns all filesystem paths under `.ralpher/projects/{project_id}/` via properties (`plan_md`, `tasks_json`, `progress_md`, `prompt_md`, `questions_json`, `current_task_json`, `config_toml`) and load/save helpers for `Tasks`, `Questions`, `ProjectConfig`, and `current_task`. `Task` has `id`, `title`, `description`, `acceptance_criteria`, and a `passes` boolean — the loop picks the first failing task each iteration. `ProjectConfig` stores `base_branch` and `target_branch` for the run. `Project.backend` (a `BackendKind` = `"claude-code" | "antigravity"`) records which backend drives the run. Backend resolution lives here too: `normalize_backend` maps CLI/settings aliases (`cc`, `agy`, …) to the canonical value, `Settings.backend` (alias-normalizing validator) is the per-checkout default, and `resolve_backend(cli)` implements flag-wins-then-settings. `Project.jj` records whether the agent drives `jj` instead of `git`; `resolve_jj(cli)` / `Settings.jj` (default `False`) resolve it flag-wins-then-settings, exactly like `sandbox`. `Settings.models` holds per-kind model **pins** (or a single string applied to all kinds) and nothing else — which model a kind gets by default is each backend's own business (`Backend.default_models`), not this module's; see Backends below.

### Plan flow — [ralpher/plan/](ralpher/plan/)
- [plan.py](ralpher/plan/plan.py) initializes the project directory + git branches, then invokes the agent with the rendered `plan` prompt via `run_agent_plan_mode` (Q&A loop — the agent can return either a finished plan or clarification questions, which are prompted to the user interactively).
- [refine.py](ralpher/plan/refine.py) runs the rendered `refine` prompt against an existing plan.
- [extract.py](ralpher/plan/extract.py) parses `PLAN.md` into structured `Tasks` JSON via the agent with a JSON schema; retries up to 3 attempts.

### Loop execution — [ralpher/loop/](ralpher/loop/)
- [loop.py](ralpher/loop/loop.py) `run_ralph_loop` is the main driver: calls `prepare`, then iterates until `max_iterations` (default 30) or all tasks pass. Each iteration picks the first failing task, invokes `iterate`, and reloads `tasks.json` to check progress.
- [iterate.py](ralpher/loop/iterate.py) writes `current_task.json`, calls the agent with the rendered `iterate` prompt and a `ProgressReport { notes }` schema, then verifies with the rendered `verify` prompt and a `Result { task_passed }` schema, then updates `tasks.json`. **The agent never writes `progress.md`** — it reads it and hands its entry back as structured output; ralpher appends `notes` under a timestamped `## <time> - <task id>` heading via `_append_progress`. The verifier's verdict is appended the same way by `_append_verifier_notes`.
- [prepare.py](ralpher/loop/prepare.py) handles first-run setup (extracting tasks, initializing progress).

### Prompts — [ralpher/prompts/](ralpher/prompts/)
`render_prompt(name, **vars)` renders a Jinja2 template in [ralpher/prompts/](ralpher/prompts/) (`plan.md`, `refine.md`, `extract-tasks.md`, `iterate.md`, `verify.md`) and returns the result, which callers pass to `run_agent` / `run_agent_plan_mode` as the **initial prompt**. The templates are the actual prompts that drive the agent — most behavior lives in markdown, not Python. They reference the project's files by absolute path (rendered from `Project` properties), and `plan.md`/`refine.md` embed the `plan-structure.md` reference doc inline (its full text is injected as the `plan_structure` Jinja global) rather than asking the agent to read it — so the agent never needs file access outside the run's workspace (which the antigravity backend enforces). The Jinja env uses `StrictUndefined`, so a template variable that a caller forgets to pass raises at render time.

`plan.md`, `refine.md`, `iterate.md`, and `verify.md` each take a `jj` boolean (rendered from `Project.jj`) that switches the version-control instructions between `git` and `jj` — the commit command in `iterate.md`, the history-inspection commands in `verify.md`, and a "use jj, not git" note in all four. With `jj=False` every one of them renders byte-identically to the pre-`--jj` prompt, so the flag is a strict no-op when off; keep it that way by guarding new VCS wording with `{%- if jj %}` rather than rewording the git path. `iterate.md` also takes a `context_file` string — the per-directory context file the running CLI reads (`CLAUDE.md` for `claude-code`, `GEMINI.md` for `antigravity`), rendered from `backend.context_file(project.backend)` so the agent updates the file its own CLI will pick up later. Never hardcode `CLAUDE.md` in a prompt; use the variable. Adapted from [snarktank/ralph](https://github.com/snarktank/ralph). (This replaces the former `--plugin-dir`-loaded `/ralpher:*` skills.)

### Backends — [ralpher/backend/](ralpher/backend/)
The single abstraction boundary for invoking a coding agent. Callers import `run_agent` / `run_agent_plan_mode` from the package façade ([__init__.py](ralpher/backend/__init__.py)) and never touch a specific backend; `get_backend(project)` looks the class up in the `BACKENDS` registry by `project.backend` and instantiates it.

A backend is **a CLI driven as a subprocess** — no vendor SDK is imported anywhere, which is why the only runtime dependencies are the CLI executables themselves.

- [base.py](ralpher/backend/base.py) — the `Backend` ABC and everything the backends share: resolving the model + effort for a kind, creating `.ralpher/projects/{id}/logs/{kind}-{timestamp}.log`, spawning the CLI (`asyncio.create_subprocess_exec`, stdout and stderr drained concurrently, a 32 MiB line limit since one JSONL record can hold a whole assistant message), tee'ing every stdout line to the log as it arrives, funnelling a non-zero exit / missing result / error result into `fail()`, validating structured output against the caller's pydantic schema, and the plan-mode Q&A loop. Also defines `AgentResult`, the normalized terminal record (`session_id`, `structured_output`, `is_error`, `error`).
- Subclasses implement exactly two things: `build_command(...)` (the argv for one turn) and `read_result(record)` (recognize this CLI's terminal result record, return an `AgentResult`). Add a new flag there, not in the driver.
- Each backend also **configures its own models**: `default_models` maps a kind (`plan`, `refine`, `loop`, `verify`, `extract-tasks`) to a model spec, and `effort_levels` lists the reasoning-effort levels that CLI accepts. It also declares `context_file`, the name of the per-directory context file that CLI reads (`CLAUDE.md` / `GEMINI.md`), exposed to prompt callers as `backend.context_file(kind)`. None of these tables live in [models.py](ralpher/models.py) — adding a backend means adding a class, not editing a shared dict.
- **Model resolution** (`Backend._resolve_model`) picks the first of: the explicitly passed `model`, a `models` pin in `.ralpher/settings.toml` (either a table of per-kind pins or a single string for all kinds), this backend's `default_models`. The reasoning effort rides on that spec as a trailing `:<level>` suffix which `Backend.split_effort` peels off, and both CLIs take it as `--effort`. A level the backend doesn't list stays part of the model name — as does the bracketed `[1m]` context-window suffix on a Claude model, which is never a level. A spec with no suffix leaves `--effort` off entirely, so the CLI's own default applies; that's why the `claude-code` defaults are bare (its default is `high`) while the `antigravity` ones pin `:high`/`:medium`. `agy models` lists the names that backend accepts.
- [common.py](ralpher/backend/common.py) — backend-agnostic plan-mode schema (`Plan`/`PlanOrQuestions`) + the `ask_user_questions` clarification UX, which renders the questions with `QuestionsPrompt` (see below) and returns the answers as JSON for the next turn's prompt.

### Clarification-question TUI — [ralpher/utils/questions_ui.py](ralpher/utils/questions_ui.py)
`QuestionsPrompt` is the tabbed prompt behind `ask_user_questions`, modelled on Claude Code's own question UI: one mouse-clickable tab per question, the options listed below with their descriptions, and a final `Submit` tab that reviews every answer. It is a single `prompt_toolkit` `Application` (`mouse_support=True`, `erase_when_done=True`) — arrow keys / `tab` move between tabs, `↑↓` and digits pick an option, the last option (`Other`) swaps in a free-form `TextArea`, and `ctrl-c` raises `KeyboardInterrupt`. All rendering goes through `_fragments()`, which returns `(style, text, mouse_handler)` tuples, so a click and a key press take exactly the same state-transition path (`_goto`, `_select_row`, `_confirm`). Mouse clicks need the terminal to answer CPR (prompt_toolkit drops them when the layout's screen position is unknown); keyboard control always works. Questions with no options are dropped up front — an empty list means no prompt is shown at all. Tests drive the keyboard flows through a pipe input and the mouse by invoking the handler on the rendered fragment ([test_questions_ui.py](tests/test_questions_ui.py)); `_qui.py` (gitignored) is an interactive demo: `uv run python _qui.py`.

The log's first line is the initial prompt, the second a `{"command": [...]}` record with the prompt elided (it is already logged in full), then the CLI's raw JSONL stream — so a log is both tail-able mid-run and reproducible by hand.

### Claude backend — [ralpher/backend/claude.py](ralpher/backend/claude.py)
`ClaudeBackend` shells out to `claude`. Key flags:
- `--output-format stream-json --verbose`, prompt passed **positionally, last** (so no variadic option can swallow it)
- `--json-schema <schema>` for structured output; Claude answers with a `{"type": "result", …}` record carrying `structured_output`
- `--permission-mode bypassPermissions` + `--dangerously-skip-permissions`, or `--permission-mode dontAsk` with `--tools=`/`--allowed-tools=` set to `READONLY_TOOLS` (or the caller's `tools`) when `readonly=True`. The `=` form is required: both options are variadic and would otherwise eat the positional prompt.
- `--effort <level>` when the resolved model spec carries a `:<level>` suffix; omitted for a bare model, leaving the CLI's default effort (`high`)
- `--resume <session_id>` for Q&A continuation in plan mode
- `--settings <inline json>` — see below. Plus `--setting-sources user,project,local` so the run isn't hermetic: the user's `.claude/settings.json` (e.g. a `sandbox.network` allowlist) is loaded and merged.

The `.ralpher` directory is kept read-only to the `claude` subprocess via `permissions.deny` rules in that inline settings JSON (`_settings_json`) — deny rules are a hard block even under `bypassPermissions`, so Claude can read its plan/task/progress files but never write into `.ralpher`. When `project.sandbox` is true the same JSON also carries `sandbox: {enabled: true, network: {allowedDomains: ["*"]}}`, which runs the Bash tool in an OS sandbox so the deny rule is enforced against shell writes too (the tool-path deny alone doesn't cover arbitrary Bash).

`Project.sandbox` defaults to `False`; only the `loop` command opts a run in — via the `--sandbox/--no-sandbox` flag, which falls back to `Settings.sandbox` (loaded from `.ralpher/settings.toml`, default `True`) when neither flag is given.

### Antigravity backend — [ralpher/backend/antigravity.py](ralpher/backend/antigravity.py)
`AntigravityBackend` shells out to `agy`, whose CLI is close enough to `claude`'s that most flags map one-to-one (`--output-format stream-json`, `--json-schema`, `--model`, `--effort`, `--dangerously-skip-permissions`). Where they differ:
- The prompt is the **value of `--print`**, not a positional argument; `--print-timeout 1h` is passed so long agent turns do not hit `agy`'s 5-minute default timeout.
- The conversation handle is `--conversation <id>` (claude: `--resume`), and it arrives as `conversation_id` on the result record.
- The stream-json envelope is `{"event": "result", "result": {…}}` rather than a flat `{"type": "result", …}`; success is `status == "SUCCESS"`.
- There is no per-tool flag, so `readonly=True` becomes `--mode plan`, which soft-denies every file write *even under* `--dangerously-skip-permissions` (verified). The `tools` argument is accepted for signature parity and ignored.
- `--add-dir <cwd>` confines file access to the run's workspace, and `project.sandbox` maps to `agy --sandbox`.

**Known gap:** the `.ralpher` directory cannot be made read-only for this backend. `agy` has no inline-settings flag to carry per-run deny rules, and its permission config is global to the user's install, which ralpher will not edit. Read-only turns are still write-free via `--mode plan`, but an implementation turn can write into `.ralpher` here where claude is hard-blocked.

### Git branch management — [ralpher/utils/git.py](ralpher/utils/git.py)
Each project runs on `ralph/{project_id}`, forked from a resolved base branch (`--base-branch`, else `main`, else `master`). `checkout_branch` auto-inits the repo with an empty commit if none exists. A `.no-branch` sentinel file in the repo root disables automatic branch creation (useful for repos that should stay on a single branch).

**`--jj` switches the agent, not ralpher.** Ralpher's own branch bookkeeping stays on `git` even under `--jj`, so a jj run must be in a git-colocated workspace (`jj git init --colocate`); `check_jj_prerequisites` enforces that up front (jj on PATH → inside a jj repo → `.git` at `jj root`) rather than letting `_ensure_repo` `git init` a second repository inside a jj-only workspace.

### Hooks — [ralpher/utils/hooks/](ralpher/utils/hooks/)
`HooksManager` dispatches lifecycle callbacks (`on_loop_start`, `on_iteration_start/end`, `on_error`, `on_loop_end`) to registered hooks. `NotionHooks` syncs task status/progress to a Notion page — configured via `RALPHER_NOTION_TOKEN` and `RALPHER_NOTION_PARENT_PAGE_ID` in `.env` (loaded by `load_dotenv` in the `loop` command).

## Key Patterns

- **Structured output over text parsing.** Anywhere the agent needs to return data, pass a Pydantic model as `schema=` to `run_agent` — both CLIs take the JSON schema via `--json-schema` and echo the answer back on their result record, which the driver validates against the model. Avoid regex/markdown parsing of stdout.
- **Project is the bag of paths.** Don't hardcode paths under `.ralpher/projects/...`; go through `Project` properties (the root comes from `ralpher_root()`) so layout changes stay local to [models.py](ralpher/models.py).
- **Tests mock the agent + filesystem.** No real `claude`/`agy` invocations in [tests/](tests/). When adding loop/plan behavior, patch `run_agent` / `run_agent_plan_mode` and assert on the prompt + schema arguments. Backend-level tests ([test_backends.py](tests/test_backends.py)) assert on argv from `build_command` and on `read_result` directly; the shared driver is exercised against a stub CLI script that replays a canned JSONL stream.
- **A test that needs a real CLI skips when it is missing.** The suite must stay green on a checkout with neither `claude` nor `agy` installed, so a test that genuinely shells out to one (or depends on it being on PATH) carries `@pytest.mark.requires_cli("claude")` — the hook in [tests/conftest.py](tests/conftest.py) skips it when the executable isn't there. Anything that only *reasons* about the CLIs (auto-detection, prerequisite checks) monkeypatches `shutil.which` instead and stays unmarked.
- **Async all the way down.** Every agent-touching function is `async`; CLI handlers use `asyncio.run()` as the single bridge. The agent subprocess is spawned with `asyncio.create_subprocess_exec` — don't introduce a blocking `subprocess.run` for it; only the thin git helpers are sync.
- **Rich + yaspin for UX.** Progress is shown via `rich.print` and `Spinner` (wraps the subprocess with humorous status messages). Raw agent stdout/stderr goes to the log file, not the terminal.
