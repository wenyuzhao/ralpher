---
name: extract-tasks
description: Extract structured tasks from a project plan.
disable-model-invocation: true
---

# Extract Tasks from a Project Plan

Extract all the tasks from an existing Project Plan to the tasks.json format that Ralph uses for autonomous execution.

---

## The Job

Take a Project Plan (markdown file or text) and convert it to `.ralpher/projects/$0/tasks.json`.

---

## The Project Plan Input

@.ralpher/projects/$0/PLAN.md

---

## Output Format

```json
{
  "tasks": [
    {
      "id": "T-001",
      "title": "[Task title]",
      "description": "Clear, concise explanation of what needs to be done and why",
      "acceptance_criteria": [
        "Criterion 1",
        "Criterion 2",
        "Typecheck passes"
      ],
      "passes": false
    }
  ]
}
```

Output File: .ralpher/projects/$0/tasks.json

---

## Conversion Rules

1. **Each task becomes one JSON entry**
2. **IDs**: Sequential (T-001, T-002, etc.)
3. **Sequential Order**: The task order in the Project Plan should be preserved in the tasks.json (no reordering)
4. **All tasks**: `passes: false`

## Example

**Output tasks.json:**

```json
{
  "tasks": [
    {
      "id": "T-001",
      "title": "Add status field to tasks table",
      "description": "Add a status column to the tasks database table to persist task progress state.",
      "acceptance_criteria": [
        "Add status column: 'pending' | 'in_progress' | 'done' (default 'pending')",
        "Generate and run migration successfully",
        "Typecheck passes"
      ],
      "passes": false
    },
    {
      "id": "T-002",
      "title": "Display status badge on task cards",
      "description": "Show a colored status badge on each task card for quick visual identification.",
      "acceptance_criteria": [
        "Each task card shows colored status badge",
        "Badge colors: gray=pending, blue=in_progress, green=done",
        "Typecheck passes",
        "Verify in browser using dev-browser skill"
      ],
      "passes": false
    },
    // ... other tasks
  ]
}
```

---

## Checklist Before Saving

Before writing tasks.json, verify:

- [ ] Extracted all tasks from the Project Plan (no missing or additional tasks)
- [ ] Tasks have the same order as in the Project Plan (no reordering)
- [ ] Faithfully preserved all details from the Project Plan in the task descriptions and acceptance criteria
