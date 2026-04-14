# Ralpher

A CLI tool that orchestrates [Claude Code](https://docs.anthropic.com/en/docs/claude-code) for autonomous software development. Give it a prompt, and it generates a Project Plan, breaks it into tasks, then runs iterative Claude development loops to implement each one.

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

## Acknowledgements

This project draws its design and some of its prompts from [snarktank/ralph](https://github.com/snarktank/ralph).
