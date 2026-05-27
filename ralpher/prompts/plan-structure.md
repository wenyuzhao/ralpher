# Project Plan Structure

Generate the Project Plan with these sections:

## 1. Introduction/Overview
Brief description of the feature and the problem it solves.

## 2. Goals
Specific, measurable objectives (bullet list).

## 3. Design
High-level software design covering architecture, system components, and API contracts. This section bridges goals and implementation by describing *how* the system will be structured.

Include as applicable:
- **Architecture:** Key components/modules and how they interact (e.g., client → API → service → database). Use a Mermaid diagram (recommended) or description of the data flow when possible.
- **Source Layout:** New or modified files, directories, and modules. Describe where code lives and how it's organized (e.g., "new `src/priority/` module with `model.py`, `service.py`, `routes.py`"). Reference existing files being changed.
- **Data Model:** New or modified entities, their fields, and relationships.
- **API Design:** New or modified endpoints/interfaces with method, path, request/response shape, and key behaviors.
- **Key Design Decisions:** Important trade-offs or choices (e.g., "polling vs. WebSockets", "separate table vs. JSON column") with brief rationale.

**Design principles — keep these in mind:**
- Faithfully follow the user's prompt and answers to questions. The design must serve the user's stated goals.
- Prioritize sound software engineering (correctness, maintainability, clarity) over implementation speed or ease.
- Refactor existing code and architecture when the current design doesn't cleanly support the new feature. Don't bolt on workarounds.
- Favor simplicity and user-friendliness over over-engineering. Build what's needed, not what's hypothetically useful.
- Prefer extending or reusing existing patterns and components over introducing new abstractions.
- Design for testability — structures should be easy to unit test without heavy mocking or setup.
- Consider edge cases and error states upfront, not as afterthoughts during implementation.

Keep it concise — enough for a developer to understand the overall shape before reading individual tasks.

## 4. Tasks
Each task needs:
- **Title:** Short descriptive name
- **Description:** Clear, concise explanation of what needs to be done and why
- **Acceptance Criteria:** Verifiable checklist of what "done" means

IMPORTANT: Each task should be small and fine-grained enough to implement in one focused session.

**Format:**
```markdown
### `T-001` - [Title]
**Description:** Clear, concise explanation of what needs to be done and why.

**Acceptance Criteria:**
- Specific verifiable criterion
- Another criterion
- Typecheck/lint passes
- **[UI tasks only]** Verify in browser using dev-browser skill
```

**Important:**
- Each task should be small and fine-grained enough to implement in one focused session. See **task size** section below.
- Tasks should be ordered. See  **task ordering** section below.
- Acceptance criteria must be verifiable, not vague. "Works correctly" is bad. "Button shows confirmation dialog before deleting" is good. See  **acceptance criteria** section below
- When possible, acceptance criteria should include unit tests, integration tests, or manually-performed tests that can be performed by yourself using skills or tools.
- **For any task with UI changes:** Always include "Verify in browser using dev-browser skill" as acceptance criteria. This ensures visual verification of frontend work.

### Task Size: The Number One Rule

**Each task must be completable in ONE Ralph iteration (one context window).**

Ralph spawns a fresh instance per iteration with no memory of previous work. If a task is too big, the LLM runs out of context before finishing and produces broken code.

**Right-sized tasks**
- Add a database column and migration
- Add a UI component to an existing page
- Update a server action with new logic
- Add a filter dropdown to a list

**Too big (split these)**
- "Build the entire dashboard" - Split into: schema, queries, UI components, filters
- "Add authentication" - Split into: schema, middleware, login UI, session handling
- "Refactor the API" - Split into one task per endpoint or pattern

**Rule of thumb:** If you cannot describe the change in 2-3 sentences, it is too big.

### Task Ordering: Dependencies First

Tasks execute in sequential order. Earlier tasks must not depend on later ones.

**Correct order:**
1. Schema/database changes (migrations)
2. Server actions / backend logic
3. UI components that use the backend
4. Dashboard/summary views that aggregate data

**Wrong order:**
1. UI component (depends on schema that does not exist yet)
2. Schema change

### Acceptance Criteria: Must Be Verifiable

Each criterion must be something Ralph can CHECK, not something vague.

**Good criteria (verifiable):**
- "Add `status` column to tasks table with default 'pending'"
- "Filter dropdown has options: All, Active, Completed"
- "Clicking delete shows confirmation dialog"
- "Typecheck passes"
- "Tests pass"

**Bad criteria (vague):**
- "Works correctly"
- "User can do X easily"
- "Good UX"
- "Handles edge cases"

**Always include as final criterion when applicable:**
- Typecheck passes
- Tests, unit tests, or integration tests passes

For tasks with testable logic, also include:
```
"Tests pass"
```

**For tasks that change UI, also include:**
```
"Verify in browser using dev-browser skill"
```

Frontend tasks are NOT complete until visually verified. Ralph will use the dev-browser skill to navigate to the page, interact with the UI, and confirm changes work.

## 5. Functional Requirements
Numbered list of specific functionalities:
- "FR-1: The system must allow users to..."
- "FR-2: When a user clicks X, the system must..."

Be explicit and unambiguous.

## 6. Non-Goals (Out of Scope)
What this feature will NOT include. Critical for managing scope.

## 7. Design Considerations (Optional)
- UI/UX requirements
- Link to mockups if available
- Relevant existing components to reuse

## 8. Technical Considerations (Optional)
- Known constraints or dependencies
- Integration points with existing systems
- Performance requirements

## 9. Success Metrics
How will success be measured?
- "Reduce time to complete X by 50%"
- "Increase conversion rate by 10%"

## 10. Open Questions
Remaining questions or areas needing clarification.

---

# Writing for Junior Developers

The Project Plan reader may be a junior developer or AI agent. Therefore:

- Be explicit and unambiguous
- Avoid jargon or explain it
- Provide enough detail to understand purpose and core logic
- Number requirements for easy reference
- Use concrete examples where helpful

---

# Example Project Plan

```markdown
# Project Plan: Task Priority System

## Introduction

Add priority levels to tasks so users can focus on what matters most. Tasks can be marked as high, medium, or low priority, with visual indicators and filtering to help users manage their workload effectively.

## Goals

- Allow assigning priority (high/medium/low) to any task
- Provide clear visual differentiation between priority levels
- Enable filtering and sorting by priority
- Default new tasks to medium priority

## Design

**Architecture:** Priority is a persisted property on the task entity. The flow is: UI priority selector → API PATCH endpoint → database column. No new services or modules needed — this extends the existing task CRUD.

**Source Layout:**
- `db/migrations/003_add_priority.sql` — new migration file.
- `src/models/task.py` — add `priority` field to the Task model.
- `src/api/tasks.py` — extend existing PATCH/GET handlers with priority filtering.
- `src/components/TaskCard.tsx` — add priority badge to existing card component.
- `src/components/PriorityFilter.tsx` — new filter dropdown component.

**Data Model:**
- `tasks` table gains a `priority` column: enum `'high' | 'medium' | 'low'`, default `'medium'`, not null.

**API Design:**
- Existing `PATCH /api/tasks/:id` accepts an optional `priority` field in the request body.
- `GET /api/tasks` response includes `priority` on each task object.
- `GET /api/tasks?priority=high` filters by priority level.

**Key Design Decisions:**
- Priority stored as a database column (not computed) so it can be indexed and queried efficiently.
- Reuse the existing badge component with color variants rather than creating a new component.
- Filter state managed via URL search params for shareability and back-button support.

## Tasks

### `T-001` - Add priority field to database
**Description:** Add a priority column to the tasks database table so that task priority persists across sessions.

**Acceptance Criteria:**
- Add priority column to tasks table: 'high' | 'medium' | 'low' (default 'medium')
- Generate and run migration successfully
- Typecheck passes

### `T-002` - Display priority indicator on task cards
**Description:** Show a colored priority badge on each task card for quick visual identification of priority level.

**Acceptance Criteria:**
- Each task card shows colored priority badge (red=high, yellow=medium, gray=low)
- Priority visible without hovering or clicking
- Typecheck passes
- Verify in browser using dev-browser skill

### `T-003` - Add priority selector to task edit
**Description:** Add a priority dropdown to the task edit modal that allows changing a task's priority level.

**Acceptance Criteria:**
- Priority dropdown in task edit modal
- Shows current priority as selected
- Saves immediately on selection change
- Typecheck passes
- Verify in browser using dev-browser skill

### `T-004` - Filter tasks by priority
**Description:** Add a priority filter dropdown to the task list that filters tasks by their priority level.

**Acceptance Criteria:**
- Filter dropdown with options: All | High | Medium | Low
- Filter persists in URL params
- Empty state message when no tasks match filter
- Typecheck passes
- Verify in browser using dev-browser skill

## Functional Requirements

- FR-1: Add `priority` field to tasks table ('high' | 'medium' | 'low', default 'medium')
- FR-2: Display colored priority badge on each task card
- FR-3: Include priority selector in task edit modal
- FR-4: Add priority filter dropdown to task list header
- FR-5: Sort by priority within each status column (high to medium to low)

## Non-Goals

- No priority-based notifications or reminders
- No automatic priority assignment based on due date
- No priority inheritance for subtasks

## Technical Considerations

- Reuse existing badge component with color variants
- Filter state managed via URL search params
- Priority stored in database, not computed

## Success Metrics

- Users can change priority in under 2 clicks
- High-priority tasks immediately visible at top of lists
- No regression in task list performance

## Open Questions

- Should priority affect task ordering within a column?
- Should we add keyboard shortcuts for priority changes?
```

---

# Checklist

Always ensure the following:

- [ ] Incorporated user's instructions or answers in the project plan
- [ ] Tasks are small and specific
- [ ] Functional requirements are numbered and unambiguous
- [ ] Non-goals section defines clear boundaries
