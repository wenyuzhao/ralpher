# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Ralpher is a Python CLI tool that orchestrates a coding agent for autonomous software development. From a user prompt it generates a plan in two halves — a `design.md` design document and a structured `tasks.toml` task list, both returned by a single planning session — then runs an iterative Ralph-loop where the agent implements one task at a time on a dedicated git branch. All AI work is delegated to an agent backend — either Claude Code (the `claude` CLI) or Google Antigravity (the `agy` CLI). Both are driven as subprocesses; there is no SDK or direct API integration. The backend is selected per run by the `--backend` flag (else the `backend` key in `.ralpher/settings.toml`) — see the Backends section under Architecture.

Two axes cross here, and keeping them apart is the point: an **agent** is *what* is asked (planner, refiner, worker, verifier — see Agents) and a **backend** is *which CLI* does it. Every agent runs on whichever backend the run selected.

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
- **Agents are declarations.** An agent says *which* prompt, schema, and flags it wants; the
  running of a turn belongs to the backend. A new per-role knob is a field on `AgentSettings`
  resolved in [agents/base.py](ralpher/agents/base.py), not an `if role == …` anywhere.
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
Typer app with a `DefaultCommandGroup` that routes unknown first args to a `run` default command. Subcommands: `plan`, `refine`, `loop`. Entry point `ralpher` → `ralpher.main:main`. All handlers are sync Typer callbacks that bridge to async via `asyncio.run()`. Every command takes `--backend` / `-b` (`BackendOption`); each resolves the backend via `_resolve_backend_or_fail` (flag → `resolve_backend` → settings/default), checks its prerequisites with `check_prerequisites`, and stores the result on `Project.backend`. `plan`, `refine`, and `loop` additionally take `--jj/--no-jj` (`JjOption`), resolved the same way by `_resolve_jj_or_fail` (flag → `resolve_jj` → settings, then `check_jj_prerequisites`) and stored on `Project.jj`.

### Project state — [ralpher/models.py](ralpher/models.py)
The `Project` Pydantic model is the central handle for a run. It owns all filesystem paths under `.ralpher/projects/{project_id}/` via properties (`design_md`, `tasks_toml`, `tasks_md`, `progress_md`, `prompt_md`, `questions_json`, `current_task_toml`, `config_toml`) and load/save helpers for `Tasks`, `Questions`, `ProjectConfig`, and `current_task`. `Project.save_tasks` is the single writer of the task list: it dumps `tasks.toml` **and** rewrites `tasks.md` from `Tasks.to_markdown()` — a human-readable mirror (checklist + one section per task) that nothing ever reads back, so the two can't drift. Never write `tasks.toml` directly. `PlannedTask` has `id`, `title`, `description`, and `acceptance_criteria` — it is exactly what the planning agent returns, so `passed` stays out of the schema it is given; `Task` subclasses it to add the `passed` boolean (a record of one past verification, not a live property; it validates from the legacy name `passes` too, so a `tasks.toml` written before the rename still loads) plus `failures`, the count of verifier rejections this task has collected, and the loop picks the first failing task each iteration. `failures` carries `exclude_if=lambda v: v == 0`, so a task nobody has failed dumps with no `failures` key at all (and `to_markdown` guards its "Verification failures" line the same way) — a clean task list serializes exactly as it did before the counter existed. `Project.save_planned_tasks` writes a freshly planned list to `tasks.toml`, carrying `passed` over for task ids that survive so a mid-run `refine` doesn't re-run finished work; the failure count rides along only for those frozen (already-passed) tasks, since a pending id may have been re-planned into different work. `ProjectConfig` stores `base_branch` and `target_branch` for the run. `Project.backend` (a `BackendKind` = `"claude-code" | "antigravity"`) records which backend drives the run. Backend resolution lives here too: `normalize_backend` maps CLI/settings aliases (`cc`, `agy`, …) to the canonical value, `Settings.backend` (alias-normalizing validator) is the per-checkout default, and `resolve_backend(cli)` implements flag-wins-then-settings. `Project.jj` records whether the agent drives `jj` instead of `git`; `resolve_jj(cli)` / `Settings.jj` (default `False`) resolve it flag-wins-then-settings, exactly like `sandbox`.

`AgentRole` (`"planner" | "refiner" | "worker" | "verifier"`, enumerated by `AGENT_ROLES`) lives here too — it is the key for everything kept per agent, so it is defined below the settings that use it rather than in [agents/](ralpher/agents/), which imports this module. **There are no role aliases**: a role is named by exactly one string, everywhere. `Settings.model` is a single model **pin** applied to every role, and `Settings.agents` maps a role to an `AgentSettings` (`model`, `readonly`, `tools`, `extra_args`, `max_corrections`) — all opt-in, all resolved in [agents/base.py](ralpher/agents/base.py). `Settings.get_model(role)` implements role-pin-then-global-pin; what a role gets when neither is set is each backend's own business (`Backend.default_models`), not this module's. An unknown role in an `[agents.<role>]` table is a validation error, so a typo is reported rather than silently ignored.

### Agents — [ralpher/agents/](ralpher/agents/)
The four jobs ralpher hands to a coding agent. **An agent is *what* is asked; a backend is *which CLI* does it** — the two compose, so every agent runs on whichever backend the project selected. Each is a subclass of `Agent` ([base.py](ralpher/agents/base.py)) that *declares* its bundle of decisions rather than spelling them out at a call site: `role`, `template` (which prompt to render), `variables()` (with what), `readonly`/`tools`, and — for an `OutputAgent` — the `output` schema. A caller constructs one and awaits `run()`; `AGENTS` maps each `AgentRole` to its class.

- [planner.py](ralpher/agents/planner.py) `Planner` — prompt in, `design.md` + `tasks.toml` out.
- [refiner.py](ralpher/agents/refiner.py) `Refiner` — the same, re-planning only the unfinished work. Takes the refinement `input_path` and the frozen `completed` tasks as constructor arguments, and owns `check_completed_tasks` as its `validate` rule.
- [worker.py](ralpher/agents/worker.py) `Worker` — implements the current task, returns a `ProgressReport { notes }`. The only agent that writes to the repo, hence the only one that commits.
- [verifier.py](ralpher/agents/verifier.py) `Verifier` — independently decides whether that task passed, returning a `Result { task_passed, notes }`.

Two shapes sit under `Agent`, matching the two ways the backend runs a turn: `OutputAgent[T]` (one turn, structured output, returns the validated `T`) and `PlanningAgent` (the plan-mode Q&A loop, which returns nothing and instead writes both halves of the plan). Planning agents are `readonly = True` — the correction loop depends on it.

**Per-role configuration is resolved in one place.** `Agent.__init__` loads this role's `AgentSettings` (the `[agents.<role>]` table), and `resolved_readonly` / `resolved_tools` / `extra_args` / `config.model` / `config.max_corrections` are what reach the backend. A new knob is a field on `AgentSettings` plus its resolution here — never a branch on `role` in the driver, and never a check at a call site.

### Plan flow — [ralpher/plan/](ralpher/plan/)
- [plan.py](ralpher/plan/plan.py) initializes the project directory + git branches, runs the `Planner` (a Q&A loop — the agent can return either a finished plan or clarification questions, which are prompted to the user interactively), and fails unless *both* `design.md` and `tasks.toml` came out of it.
- [refine.py](ralpher/plan/refine.py) gathers the refinement instructions (the user's prompt plus any Notion comments) into a temp file and runs the `Refiner` against the existing plan, rewriting both halves.

**Refine only re-plans the unfinished work.** A refinement can land partway through a loop, so every task with `passed = true` is *frozen*: `refine_plan` hands the completed tasks to the `Refiner`, which renders them into the prompt (the `completed_tasks` template variable, which renders the "Already-Completed Tasks — Frozen" section) and enforces them in its `validate`, `check_completed_tasks`, rejecting any returned plan where a completed task is missing or came back with a different title, description, or acceptance criteria. Pending tasks stay fully re-plannable. The design document *may* contradict what a passed task built — it documents the intended final state — but the prompt requires every such change to be carried by a **new**, not-yet-passed task rather than by editing the completed one, since `save_planned_tasks` only carries `passed` across for a surviving id.

**There is no task-extraction step.** A planning session returns the design markdown and the task list together in one `Plan` structured output, so nothing ever re-parses prose back into tasks. Adding a "just re-extract the tasks" path would reintroduce exactly the drift this removed.

### Loop execution — [ralpher/loop/](ralpher/loop/)
- [loop.py](ralpher/loop/loop.py) `run_ralph_loop` is the main driver: calls `prepare`, then iterates until `max_iterations` (default 30) or all tasks pass. Each iteration picks the first failing task, invokes `iterate`, and reloads `tasks.toml` to check progress.
- [iterate.py](ralpher/loop/iterate.py) writes `current_task.toml`, runs the `Worker`, then the `Verifier` in a fresh session so it isn't biased by the worker's context, then records the verdict in `tasks.toml`: a pass flips `passed`, a failure bumps that task's `failures` count. **The agent never writes `progress.md`** — it reads it and hands its entry back as structured output; ralpher appends `notes` under a timestamped `## <time> - <task id>` heading via `_append_progress`. The verifier's verdict is appended the same way by `_append_verifier_notes`. What each agent is asked and what it must return lives in [agents/](ralpher/agents/), not here.
- [prepare.py](ralpher/loop/prepare.py) handles first-run setup: it requires `design.md` and `tasks.toml` to already exist (run `ralpher plan` first — the loop never generates them), then initializes progress and checks out the target branch.

### Prompts — [ralpher/prompts/](ralpher/prompts/)
`render_prompt(name, **vars)` renders a Jinja2 template in [ralpher/prompts/](ralpher/prompts/) (`plan.md`, `refine.md`, `iterate.md`, `verify.md`) and returns the result. Its only caller is `Agent.prompt()`, which pairs each agent's `template` with its `variables()`; the result becomes that turn's **initial prompt**. The templates are the actual prompts that drive the agent — most behavior lives in markdown, not Python. They reference the project's files by absolute path (rendered from `Project` properties), and `plan.md`/`refine.md` embed the `plan-structure.md` reference doc inline (its full text is injected as the `plan_structure` Jinja global) rather than asking the agent to read it — so the agent never needs file access outside the run's workspace (which the antigravity backend enforces). The Jinja env uses `StrictUndefined`, so a template variable that a caller forgets to pass raises at render time.

`plan.md`, `refine.md`, `iterate.md`, and `verify.md` each take a `jj` boolean (rendered from `Project.jj`) that switches the version-control instructions between `git` and `jj` — the commit command in `iterate.md`, the history-inspection commands in `verify.md`, and a "use jj, not git" note in all four. With `jj=False` every one of them renders byte-identically to the pre-`--jj` prompt, so the flag is a strict no-op when off; keep it that way by guarding new VCS wording with `{%- if jj %}` rather than rewording the git path. `refine.md`, `iterate.md`, and `verify.md` take `design_path` + `tasks_path` (both halves of the plan; `plan.md` takes only `prompt_path`, since it creates them). `refine.md` also takes `completed_tasks` (the already-passing `Task`s); with an empty list every frozen-task block disappears and the prompt renders as it did before, exactly like the `jj` flag. `iterate.md` also takes a `context_file` string — the per-directory context file the running CLI reads (`CLAUDE.md` for `claude-code`, `GEMINI.md` for `antigravity`), rendered by `Worker.variables()` from `backend.context_file(project.backend)` so the agent updates the file its own CLI will pick up later. Never hardcode `CLAUDE.md` in a prompt; use the variable. Adapted from [snarktank/ralph](https://github.com/snarktank/ralph). (This replaces the former `--plugin-dir`-loaded `/ralpher:*` skills.)

### Backends — [ralpher/backend/](ralpher/backend/)
The single abstraction boundary for invoking a coding-agent CLI. Its callers are the agents in [ralpher/agents/](ralpher/agents/), which reach it through `run_agent` / `run_agent_plan_mode` on the package façade ([__init__.py](ralpher/backend/__init__.py)) and never touch a specific backend; `get_backend(project)` looks the class up in the `BACKENDS` registry by `project.backend` and instantiates it. Both entry points take the `role` running the turn, plus the knobs that role resolved (`model`, `readonly`, `tools`, `extra_args`, and `max_corrections` in plan mode).

A backend is **a CLI driven as a subprocess** — no vendor SDK is imported anywhere, which is why the only runtime dependencies are the CLI executables themselves.

- [base.py](ralpher/backend/base.py) — the `Backend` ABC and everything the backends share: resolving the model + effort for a role, creating `.ralpher/projects/{id}/logs/{role}-{timestamp}.log`, spawning the CLI (`asyncio.create_subprocess_exec`, stdout and stderr drained concurrently, a 32 MiB line limit since one JSONL record can hold a whole assistant message), tee'ing every stdout line to the log as it arrives, funnelling a non-zero exit / missing result / error result into `fail()`, validating structured output against the caller's pydantic schema, and the plan-mode Q&A loop. Also defines `AgentResult`, the normalized terminal record (`session_id`, `structured_output`, `is_error`, `error`).
- Subclasses implement exactly two things: `build_command(...)` (the argv for one turn) and `read_result(record)` (recognize this CLI's terminal result record, return an `AgentResult`). Add a new flag there, not in the driver.
- Each backend also **configures its own models**: `default_models` maps an `AgentRole` to a model spec, and `effort_levels` lists the reasoning-effort levels that CLI accepts. It also declares `context_file`, the name of the per-directory context file that CLI reads (`CLAUDE.md` / `GEMINI.md`), exposed to prompt callers as `backend.context_file(kind)`. None of these tables live in [models.py](ralpher/models.py) — adding a backend means adding a class, not editing a shared dict.
- **Model resolution** (`Backend._resolve_model`) picks the first of: the explicitly passed `model` (where the agent supplies its `[agents.<role>].model`), the global `model` pin in `.ralpher/settings.toml`, this backend's `default_models`. The reasoning effort rides on that spec as a trailing `:<level>` suffix which `Backend.split_effort` peels off, and both CLIs take it as `--effort`. A level the backend doesn't list stays part of the model name — as does the bracketed `[1m]` context-window suffix on a Claude model, which is never a level. A spec with no suffix leaves `--effort` off entirely, so the CLI's own default applies; that's why the `claude-code` defaults are bare (its default is `high`) while the `antigravity` ones pin `:high`/`:medium`. `agy models` lists the names that backend accepts.
- [common.py](ralpher/backend/common.py) — backend-agnostic plan-mode schema (`Plan`/`PlanOrQuestions`) + the `ask_user_questions` clarification UX, which renders the questions with `QuestionsPrompt` (see below) and returns the answers as JSON for the next turn's prompt.

### Plan-mode output — [ralpher/backend/common.py](ralpher/backend/common.py), [base.py](ralpher/backend/base.py)
`PlanOrQuestions` is the schema every plan-mode turn is given: either `Questions` (ask the user) or `Plan`, which carries **both** `markdown` (the design document) and `tasks` (a `list[PlannedTask]`). `Backend.run_plan_mode` writes the markdown to `Project.design_md` and the tasks via `Project.save_planned_tasks`. The prompts insist the design markdown contain no task list — the two halves must not restate each other.

**Two checks stand between a returned plan and the files.** `check_task_ids` (in [common.py](ralpher/backend/common.py)) always runs, on `plan` and `refine` alike: a plan's ids must be `T-001`, `T-002`, … matching each task's position in the list — three digits, starting at 1, no gaps, no reordering — and there may be at most `MAX_TASKS` (999) of them, since the id is only three digits wide. The loop runs the list top to bottom while `current_task.toml`, progress headings, and the Notion checklist all key off the id, so an id that disagrees with its position makes the plan's order and its numbering disagree about what runs next. On top of that, `run_plan_mode` takes an optional `validate(plan) -> str | None` callback for the caller's own rule (`refine` freezes the already-passing tasks with it; see Plan flow — keep such checks in the caller, the driver stays generic).

Either check returning a message rejects the plan and makes that message the next turn's prompt, so the agent corrects itself with its conversation intact; when both fire, both messages are sent **together**, because fixing one can break the other (renumbering vs. refine's frozen ids) and the agent needs the whole picture. After `MAX_PLAN_CORRECTIONS` rejections — or the role's own `max_corrections`, if it pins one — the run `fail()`s with the message and nothing is written.

A **correction turn is given `PlanOnly`** instead of `PlanOrQuestions` — same `plan_or_questions` field name (so the prompts' `{"plan_or_questions": {…}}` instructions still hold and the result parses identically), minus the `Questions` branch. The agent is answering a rejection of its own output there and has everything it needs to fix it; a question would only bounce the rejection back at the user. Model docstrings ride along in the JSON schema sent to the CLI, so keep them one-liners and put the reasoning in a comment above the class.

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
`HooksManager` dispatches lifecycle callbacks (`on_loop_start`, `on_iteration_start/end`, `on_error`, `on_loop_end`) to registered hooks. `NotionHooks` syncs task status/progress to a Notion page — configured via `RALPHER_NOTION_TOKEN` and `RALPHER_NOTION_PARENT_PAGE_ID` in `.env` (loaded by `load_dotenv` in the `loop` command). The page layout is [notion.md](ralpher/utils/hooks/notion.md): a `🔨 Tasks` status checklist, then expandable `📐 Design` and `📋 Task List` sections, then the prompt and progress log. [notion_comments.py](ralpher/utils/notion_comments.py) scopes `refine`'s comment pickup to the two plan sections via `PLAN_SECTION_HEADINGS` (matched as substrings — `"Task List"`, not `"Tasks"`, so the status checklist is excluded); renaming a heading in `notion.md` means updating that tuple.

## Key Patterns

- **Structured output over text parsing.** Anywhere the agent needs to return data, declare a Pydantic model as an `OutputAgent`'s `output` — both CLIs take the JSON schema via `--json-schema` and echo the answer back on their result record, which the driver validates against the model. Avoid regex/markdown parsing of stdout.
- **Project is the bag of paths.** Don't hardcode paths under `.ralpher/projects/...`; go through `Project` properties (the root comes from `ralpher_root()`) so layout changes stay local to [models.py](ralpher/models.py).
- **Tests mock the agent + filesystem.** No real `claude`/`agy` invocations in [tests/](tests/). When adding loop/plan behavior, patch `ralpher.agents.base.run_agent` / `ralpher.agents.base.run_agent_plan_mode` — the one place every agent hands its turn to a backend — and assert on the prompt + schema arguments. What an agent declares and how its settings resolve belongs in [test_agents.py](tests/test_agents.py). Backend-level tests ([test_backends.py](tests/test_backends.py)) assert on argv from `build_command` and on `read_result` directly; the shared driver is exercised against a stub CLI script that replays a canned JSONL stream.
- **A test that needs a real CLI skips when it is missing.** The suite must stay green on a checkout with neither `claude` nor `agy` installed, so a test that genuinely shells out to one (or depends on it being on PATH) carries `@pytest.mark.requires_cli("claude")` — the hook in [tests/conftest.py](tests/conftest.py) skips it when the executable isn't there. Anything that only *reasons* about the CLIs (auto-detection, prerequisite checks) monkeypatches `shutil.which` instead and stays unmarked.
- **Async all the way down.** Every agent-touching function is `async`; CLI handlers use `asyncio.run()` as the single bridge. The agent subprocess is spawned with `asyncio.create_subprocess_exec` — don't introduce a blocking `subprocess.run` for it; only the thin git helpers are sync.
- **Rich + yaspin for UX.** Progress is shown via `rich.print` and `Spinner` (wraps the subprocess with humorous status messages). Raw agent stdout/stderr goes to the log file, not the terminal.
