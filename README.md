# Ralpher

A CLI tool that orchestrates a coding agent for autonomous software development. Give it a prompt, and it generates a design document plus a task list, then runs iterative development loops to implement each task. It can drive either [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (default) or [Google Antigravity](https://antigravity.google) — see [Backends](#backends).

Workflow: `User Prompt` ➔ `design.md` + `tasks.toml` ➔ `Ralph Wiggum Loop⁠`

## Install

```bash
pipx install ralpher
```

## Usage

```bash
# 1. Generate a design document and task list
ralpher plan "Create a TODO app" --name todo-app

# (Optional) Refine the design and tasks
ralpher refine "Use MySQL"

# 2. Run the Ralph-loop on an existing plan
ralpher loop
```

## Backends

Ralpher can drive either coding agent backend. Pick one per command with `--backend` / `-b`, or set a default in `.ralpher/settings.toml`:

Both backends are the vendor's own CLI, driven as a subprocess — ralpher bundles no agent SDK and reads no API keys, so each CLI's existing login is what authenticates a run.

| Backend | Aliases | Engine | Requirements |
| --- | --- | --- | --- |
| `claude-code` (default) | `cc` | [Claude Code](https://docs.anthropic.com/en/docs/claude-code) | `claude` CLI on `PATH`, signed in |
| `antigravity` | `agy` | [Google Antigravity](https://antigravity.google) (Gemini) | `agy` CLI on `PATH`, signed in |

```bash
# Per-run: use the antigravity backend
ralpher plan "Create a TODO app" --name todo-app --backend agy
ralpher loop -b agy
```

```toml
# .ralpher/settings.toml — set a default backend for this checkout
backend = "antigravity"
```

The `--backend` flag wins over the `backend` key in `settings.toml`, which in turn beats the `claude-code` default. Run `claude` or `agy` once to sign in before pointing ralpher at it; `agy models` lists the model names the antigravity backend accepts.

You can also pin models in `.ralpher/settings.toml`, either as a single model for all tasks or per-kind (`plan`, `refine`, `loop`, `verify`):

```toml
# .ralpher/settings.toml — use one model for all steps
models = "claude-3-7-sonnet"

# or per-kind:
# [models]
# plan = "claude-3-7-sonnet"
# verify = "claude-3-5-haiku"
```

## Jujutsu (`jj`)

If your repo is managed with [Jujutsu](https://jj-vcs.github.io/jj/), pass `--jj` so the agent commits with `jj` instead of `git`:

```bash
ralpher plan "Create a TODO app" --name todo-app --jj
ralpher loop --jj
```

```toml
# .ralpher/settings.toml — make it the default for this checkout
jj = true
```

The flag only changes what the agent is told: it commits with `jj commit`, inspects history with `jj log` / `jj diff` / `jj show`, and leaves bookmarks alone. Ralpher still creates and checks out the `ralph/{project_id}` branch with `git`, so the workspace must be **colocated** (`jj git init --colocate`) — `--jj` fails fast with an explanation if it isn't. `--no-jj` overrides the settings key for a single run.

## Extra CLI args

`extra_args` in `.ralpher/settings.toml` is appended verbatim to every backend invocation (`claude` or `agy`), for flags ralpher doesn't expose itself:

```toml
# .ralpher/settings.toml
extra_args = ["--add-dir", "/extra/path"]
```

There is no `--extra-args` CLI flag; this is settings.toml-only.

## How it works

1. **Plan generation** -- Sends your prompt to the agent, which answers with both halves of the plan in one structured response: a design document, saved to `.ralpher/projects/{project_id}/design.md`, and the ordered task list (with acceptance criteria), saved to `.ralpher/projects/{project_id}/tasks.toml`. No separate extraction pass turns prose back into tasks. A human-readable `tasks.md` is rendered next to `tasks.toml` and kept in sync on every update.
2. **Run Ralph-loop** -- Iteratively invokes the agent to implement each failing task on a dedicated git branch (`ralph/{project_id}`), passing it the design document and the task list, then verifies the result in a fresh session and records progress.

## [Notion](https://www.notion.so/) integration

Ralpher supports optional Notion integration for syncing task status. Set these in a `.env` file:

- `RALPHER_NOTION_TOKEN` -- Notion API token
- `RALPHER_NOTION_PARENT_PAGE_ID` -- Parent page for task pages

## Development

```bash
# Run tests
uv run pytest
```

## TODO

- [ ] Add git worktree support
- [ ] Create PRs automatically
- [ ] Run repeating tasks in a loop (useful for continuous optimization, refactoring, or research)
- [ ] Implement a standalone reviewer agent (or subagent) in both the planning and loop stages
- [ ] Support Gemini-CLI
- [ ] Support Codex CLI

## Acknowledgements

This project draws its design and some of its prompts from [snarktank/ralph](https://github.com/snarktank/ralph).
