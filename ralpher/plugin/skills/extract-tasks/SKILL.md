---
name: extract-tasks
description: Extract structured tasks from a project plan.
disable-model-invocation: true
---

# Extract Tasks from a Project Plan

Extract all the tasks from an existing Project Plan to the tasks.json format that Ralph uses for autonomous execution.

---

## The Job

Take a Project Plan (markdown file or text) and convert it a list of tasks in the specified JSON format.

---

## The Project Plan Input

@.ralpher/projects/$0/PLAN.md

---

## Task Format

Each task should have the following fields:
* `id`: Unique identifier (e.g., T-001, T-002, etc.)
* `title`: A concise title summarizing the task
* `description`: A clear, detailed explanation of what needs to be done and why",
* `acceptance_criteria`: A list of specific conditions that must be met for the task to be considered complete
* `passes`: set to `false` for all tasks

---

## Conversion Rules

1. **Each task becomes one JSON entry**
2. **IDs**: Sequential (T-001, T-002, etc.)
3. **Sequential Order**: The task order in the Project Plan should be preserved in the tasks.json (no reordering)
4. **All tasks**: `passes: false`

---

## Checklist

- [ ] Extracted all tasks from the Project Plan (no missing or additional tasks)
- [ ] Tasks have the same order as in the Project Plan (no reordering)
- [ ] Faithfully preserved all details from the Project Plan in the task descriptions and acceptance criteria
- [ ] Output: Use `StructuredOutput` tool WITHOUT WRITING TO ANY FILES.