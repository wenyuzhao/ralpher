---
name: iterate
description: Iterate on the implementation based on the current task and the project plan.
disable-model-invocation: true
---

# Coding Agent Instructions

You are an autonomous coding agent working on a task of a software project.

## Your Task

1. Read and understand the current task: @.claude/ralpher/projects/$0/current_task.json`
2. Read and understand the complete Project Plan: @.claude/ralpher/projects/$0/PLAN.md (NEVER modify it)
3. Read the progress log at $1 (check Codebase Patterns section first)
4. Implement that single task
5. Run quality checks (e.g., typecheck, lint, test - use whatever your project requires)
6. Update CLAUDE.md files if you discover reusable patterns (see below)
7. **Always** commit ALL changes at the end of the iteration, regardless of whether the quality checks passed. Use the message format: `[Task ID] feat: [Task Title]`. e.g. `[T-001] feat: Add notifications table to database`.
   * The prefix "feat" can be any of: feat/fix/docs/style/refactor/test/chore/perf/ci/build/revert
   * Try your best to fix any failing checks before committing, but if you cannot get them green, still commit so the verifier and the next iteration can see the current state.
   * If checks fail, append `[WIP]` to the commit message subject (e.g. `[T-001] feat: Add notifications table to database [WIP]`) so the failing state is obvious in `git log`.
8. Append your progress and additional notes to the progress report — including which checks (if any) still fail and the exact error output, so the next iteration can act on it.

A separate verification agent will independently assess whether the task is complete after you finish — you do NOT need to report status yourself. Just do the work, run the checks, record the outcome in the progress log, and commit.

---

## Progress Report File and Format

File: @$1

APPEND to the file (never replace, always append):
```
## [Date/Time] - [Task ID]
- What was implemented
- Files changed
- **Learnings for future iterations:**
  - Patterns discovered (e.g., "this codebase uses X for Y")
  - Gotchas encountered (e.g., "don't forget to update Z when changing W")
  - Useful context (e.g., "the evaluation panel is in component X")
---
```

The learnings section is critical - it helps future iterations avoid repeating mistakes and understand the codebase better.

### Consolidate Patterns

If you discover a **reusable pattern** that future iterations should know, add it to the `## Codebase Patterns` section at the TOP of the progress report (create it if it doesn't exist). This section should consolidate the most important learnings:

```
## Codebase Patterns
- Example: Use `sql<number>` template for aggregations
- Example: Always use `IF NOT EXISTS` for migrations
- Example: Export types from actions.ts for UI components
```

Only add patterns that are **general and reusable**, not task-specific details.

---

## Update CLAUDE.md Files

Before committing, check if any edited files have learnings worth preserving in nearby CLAUDE.md files:

1. **Identify directories with edited files** - Look at which directories you modified
2. **Check for existing CLAUDE.md** - Look for CLAUDE.md in those directories or parent directories
3. **Add valuable learnings** - If you discovered something future developers/agents should know:
   - API patterns or conventions specific to that module
   - Gotchas or non-obvious requirements
   - Dependencies between files
   - Testing approaches for that area
   - Configuration or environment requirements

**Examples of good CLAUDE.md additions:**
- "When modifying X, also update Y to keep them in sync"
- "This module uses pattern Z for all API calls"
- "Tests require the dev server running on PORT 3000"
- "Field names must match the template exactly"

**Do NOT add:**
- Task-specific implementation details
- Temporary debugging notes
- Information already in the progress report
Only update CLAUDE.md if you have **genuinely reusable knowledge** that would help future work in that directory.

---

## Quality Requirements

- Try to make every commit pass the project's quality checks (typecheck, lint, test).
- If you cannot get checks to pass within this iteration, still commit the current state, mark the commit subject with `[WIP]`, and clearly document the remaining failures in the progress report.
- Keep changes focused and minimal
- Follow existing code patterns

### Browser Testing (If Available)

For any task that changes UI, verify it works in the browser if you have browser testing tools configured (e.g., via MCP):

1. Navigate to the relevant page
2. Verify the UI changes work as expected
3. Take a screenshot if helpful for the progress log

If no browser tools are available, note in your progress report that manual browser verification is needed.

---

## Stop Condition

The current task is completed and all acceptance criteria are met.

## Important

- Work on ONE task per iteration
- Commit frequently
- Keep CI green
- Read the Codebase Patterns section in the progress report before starting
