# Ralpher

A CLI tool that orchestrates a coding agent for autonomous software development. Give it a prompt, and it generates a Project Plan, breaks it into tasks, then runs iterative development loops to implement each one. It can drive either [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (default) or the [Google Antigravity SDK](https://github.com/google-antigravity/antigravity-sdk-python) — see [Backends](#backends).

Workflow: `User Prompt` ➔ `Project Plan` ➔ `Ralph Wiggum Loop⁠`

## Install

```bash
pipx install ralpher
```

## Usage

```bash
# 1. Generate a Project Plan
ralpher plan "Create a TODO app" --name todo-app

# (Optional) Refine the plan
ralpher refine "Use MySQL"

# 2. Run the Ralph-loop on an existing plan
ralpher loop
```

## Backends

Ralpher can drive either coding agent backend. Pick one per command with `--backend` / `-b`, or set a default in `.ralpher/settings.json`:

| Backend | Aliases | Engine | Requirements |
| --- | --- | --- | --- |
| `claude-code` (default) | `cc` | [Claude Code](https://docs.anthropic.com/en/docs/claude-code) via the Claude Agent SDK | `claude` CLI on `PATH` |
| `antigravity` | `agy` | [Google Antigravity SDK](https://github.com/google-antigravity/antigravity-sdk-python) (Gemini) | `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) |

```bash
# Per-run: use the antigravity backend
ralpher plan "Create a TODO app" --name todo-app --backend agy
ralpher loop -b agy
```

```jsonc
// .ralpher/settings.json — set a default backend for this checkout
{
  "backend": "antigravity"
}
```

The `--backend` flag wins over the `backend` key in `settings.json`, which in turn beats the `claude-code` default. The antigravity backend reads `GEMINI_API_KEY` from the environment (or a `.env` file); get a key at <https://aistudio.google.com/app/api-keys>.

## How it works

1. **Plan generation** -- Sends your prompt to Claude to produce a structured Project Plan with tasks, saved to `.ralpher/projects/{project_id}/PLAN.md`.
2. **Run Ralph-loop**
    1. Parses the plan into a structured JSON model (project, tasks with acceptance criteria and priorities).
    2. Iteratively invokes `claude` to implement each task on a dedicated git branch (`ralph/{project_id}`), tracking progress and detecting completion.

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
