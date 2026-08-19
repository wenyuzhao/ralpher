# Refine the Project Plan

Refine the design document and task list based on user's input.

---

## The Job

1. Receive a refinement instruction from the user
2. Carefully review the current repo to understand the source code and the context
3. (Optional) Ask 3-10 essential clarifying questions if the instruction is ambiguous
  * See the "Step 2: (Optional) Clarifying Questions" section below
  * Don't ask the user to provide more details. Just provide them with a list of concrate options.
  * Use the structured output tool.
4. Generate a new design document and task list based on the user prompt and the answers (don't modify any files, just output the content following the structured output format)
  * Use the structured output tool.

**Important:** Do NOT start implementing. Just update the design document and the task list.

---

## The Original Plan

The original plan is in two files. Read both before making any changes:

- The design document: `{{ design_path }}`
- The task list: `{{ tasks_path }}`

The task list is TOML. Each task has an `id`, `title`, `description`, `acceptance_criteria`, and a `passed` flag recording whether it has already been implemented and verified.
{%- if completed_tasks %}

---

## Already-Completed Tasks — Frozen

These tasks have `passed = true`: they are already implemented, verified, and committed to the repo.
{% for task in completed_tasks %}
- `{{ task.id }}` — {{ task.title }}
{%- endfor %}

They are **frozen**. The new task list you return MUST contain every one of them exactly as it appears in the original task list: same `id`, same `title`, same `description`, same `acceptance_criteria`, and in the same relative order. Do not edit, reword, split, merge, renumber, reorder, or drop them. A plan that changes any of them is rejected and handed straight back to you.

Re-plan **only** the tasks that have not passed yet. Those you may freely rewrite, add to, reorder, or delete.

If the refinement changes something a completed task already built, do **not** edit that task. Add a **new** task — placed after the completed ones — that adjusts or re-implements the affected code, written as a change to code that already exists rather than as a fresh implementation.

Because the completed tasks keep their ids and the list must stay numbered `T-001`, `T-002`, … in order, keep them at the front of the list, in their original order, and number everything that follows on from them.
{%- endif %}

---

## User Provided Input

The user's refinement instruction is in the file `{{ input_path }}`. Read it.

---

## Step 1: Review the current repo and the original plan

The repo has been checked out to ther target branch of this project for you. Carefully review the current repo and understand the context.
{%- if jj %}

This repository is managed with [Jujutsu](https://jj-vcs.github.io/jj/): inspect its history with `jj log` / `jj diff` / `jj show` rather than `git`, and write the plan for an implementer that commits with `jj`, not `git`.
{%- endif %}

Review the original design document and task list carefully, and understand the current plan before making any changes.

---

## Step 2: (Optional) Clarifying Questions

Ask only critical questions where the user prompt is ambiguous.

To ask user questions, use the structured output tool with all the questions and finish your turn. The user will provide answers in the next turn.
All questions should have the following fields:
* `header`: A short header in 1-2 words describing the question
* `question`: The question to ask the user. It should be a multiple-choice single-answer question.
* `options`: A list of 2-6 concrete options. Each option should have:
  * `label`: A short label for the option
  * `description`: A detailed description of the option to help the user choose

If any questions are depend on the answers to other questions, please ask the dependent questions in the next turn after receiving the user's answers.

---

## Step 3: Update the Design Document and Task List

Generate the updated design document (markdown) and the updated task list (structured data). Return **both** in full, even if only one of them changed.

Follow the structure below for the list of required sections, the task fields, and an example:

<plan-structure>
{{ plan_structure }}
</plan-structure>

Strictly follow the user's instructions, and don't change unrelated parts.

You may need to add, update, remove, or reorder tasks to fit the new plan.

**Keeping task IDs stable matters.** A task that already has `passed = true` in the original task list has been implemented and verified. Keep its `id` unchanged, so it is not implemented a second time.

**The ids must still be sequential when you are done.** Whatever you add, remove, or reorder, the list you return must be numbered `T-001`, `T-002`, `T-003`, … in order, with no gaps — so after adding or dropping tasks, renumber the not-yet-passed ones to close up the sequence, and give new tasks the ids that follow the last one you kept.
{%- if completed_tasks %}

**The completed tasks listed above are frozen.** Carry each of them into the new task list verbatim, and re-plan only the tasks that have not passed. Never fold new work into a completed task; new work always goes into a new task.

**The design document must describe the intended final state — including where that differs from what is already built.** You may change the design of something a completed task implemented; the design document is the durable reference, not a record of what was done. But whenever you do, the difference must be covered by a new, not-yet-passed task. A design change to already-implemented code with no task planning its re-implementation will never be built, and the repo will silently disagree with the design document.

Before you finish, walk the design document section by section and ask, for each part that a completed task already built: did I change it? If so, is there a new task that re-implements it? Every changed part needs one.
{%- endif %}

You can do step-2 multiple times to ask more questions before making the plan.

**Important instructions for returning the plan:**
- Do NOT write the plan to any files or create any artifacts on the disk.
- You MUST return the plan using the structured output tool
- The structured output must be an object containing `plan_or_questions` formatted as a `Plan` object: `{"plan_or_questions": {"markdown": "<full markdown content of the design document>", "tasks": [{"id": "T-001", "title": "...", "description": "...", "acceptance_criteria": ["..."]}, ...]}}`.
- Do NOT put a summary, message, or file path in `markdown` -- it must contain the entire, complete markdown text of the design document.
- The design document in `markdown` must NOT contain the task list. Tasks go in `tasks` and nowhere else.
- Do NOT include a `passed` field on a task; that is tracked outside the plan.

---

## Checklist

Before outputing the new plan:

- [ ] Reviewed the repo, the original design document and task list, and any other context
- [ ] Incorporated the user's instructions
- [ ] (Optional) Asked clarifying questions and incorporated user's answers
- [ ] Did not change unrelated parts of the plan
{%- if completed_tasks %}
- [ ] Returned every already-completed task verbatim: {% for task in completed_tasks %}`{{ task.id }}`{{ ", " if not loop.last }}{% endfor %}
- [ ] Re-planned only the tasks that have not passed
- [ ] Every design change to already-implemented code is covered by a new, not-yet-passed task
{%- else %}
- [ ] Kept the IDs of already-passing tasks whose work is unchanged
{%- endif %}
- [ ] The design document follows the required structure and includes all required sections
- [ ] The design document contains no task list, task IDs, or work breakdown
- [ ] Output: Use the structured output tool to return `{"plan_or_questions": {"markdown": "...", "tasks": [...]}}` containing the complete design document markdown and the full task list (or `{"plan_or_questions": {"questions": [...]}}` if asking questions). Do NOT write to any files or create any artifacts.
