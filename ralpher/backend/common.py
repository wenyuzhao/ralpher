"""Backend-agnostic plan-mode pieces shared by every agent backend.

The plan-mode output schema (`Plan` / `PlanOrQuestions`), the task-id invariant
every plan must satisfy (`check_task_ids`), and the interactive
clarification-question UX (`ask_user_questions`) don't depend on which agent
SDK produced them, so they live here rather than in any one backend. This lets
the claude-code and antigravity backends stay independent of each other.
"""

import json

import rich
from pydantic import BaseModel, Field

from ralpher.models import PlannedTask, Questions
from ralpher.utils.questions_ui import QuestionsPrompt

# Task ids are three-digit and sequential, so `T-999` is the last one a plan can
# name. A plan that wants more tasks than that is not a plan, it is a backlog.
MAX_TASKS = 999

# The id of the nth task (1-based). The whole list is checked against this, so a
# plan's ids are always `T-001`, `T-002`, … in list order, with no gaps.
TASK_ID_FORMAT = "T-{:03d}"


class Plan(BaseModel):
    """Returned when the plan is complete: the design document plus its tasks.

    The two halves are kept apart on purpose — the markdown becomes design.md
    (durable documentation of *what* is being built and how) while the tasks
    become tasks.toml (scaffolding for this run only), so the design document
    must not restate the task list.
    """

    markdown: str = Field(
        description="The complete markdown content of the design document. DO NOT provide a summary or file path -- you MUST return the full markdown text of the design document here. It must NOT contain the task list; the tasks go in the separate 'tasks' field."
    )
    tasks: list[PlannedTask] = Field(
        description="The ordered list of implementation tasks derived from the design, each small enough to complete in one focused session. Tasks are executed in this order, so a task must never depend on a later one."
    )


class PlanOrQuestions(BaseModel):
    """Root structured output for plan mode."""

    plan_or_questions: Questions | Plan = Field(
        description="Must be either a Questions object (with a 'questions' list) if clarification is needed, or a Plan object (with a 'markdown' containing the full markdown text of the design document and a 'tasks' list of the implementation tasks)."
    )


# Note: a model's docstring is shipped to the agent as the schema's
# description, so keep the one below short and the rationale up here. `PlanOnly`
# keeps `PlanOrQuestions`' field name — so the prompt's instructions about
# returning `{"plan_or_questions": {…}}` still hold and the result parses the
# same way — but drops the `Questions` branch. It is used for a correction turn,
# where the agent is answering a rejection of its own output: it already has
# everything it needs to fix it, and a question there would only bounce the
# rejection back at the user.
class PlanOnly(BaseModel):
    """Root structured output for plan mode when only a plan is acceptable."""

    plan_or_questions: Plan = Field(
        description="A Plan object, with a 'markdown' containing the full markdown text of the design document and a 'tasks' list of the implementation tasks. Do NOT ask questions here -- fix the plan and return it."
    )


def check_task_ids(plan: Plan) -> str | None:
    """Error message if the plan's task ids break the numbering, else None.

    Every plan — from `plan` and from `refine` alike — must number its tasks
    `T-001`, `T-002`, `T-003`, … in the order the tasks appear: three digits,
    starting at one, no gaps, no reordering. The loop runs the list top to
    bottom while everything else (`current_task.toml`, progress headings, the
    Notion checklist) keys off the id, so ids that don't match their position
    make the plan's order and its numbering disagree about what runs next.

    Like `run_plan_mode`'s `validate` hook, the message is written as an
    instruction to the agent and fed back as the next turn's prompt.
    """
    if len(plan.tasks) > MAX_TASKS:
        return (
            f"The task list has {len(plan.tasks)} tasks. A plan may contain at "
            f"most {MAX_TASKS} — ids are three digits, so `{TASK_ID_FORMAT.format(MAX_TASKS)}` "
            "is the last one. Merge closely related tasks, or cut the scope of "
            "the plan, and return the complete plan again."
        )

    wrong = [
        (position, task.id, TASK_ID_FORMAT.format(position))
        for position, task in enumerate(plan.tasks, start=1)
        if task.id != TASK_ID_FORMAT.format(position)
    ]
    if not wrong:
        return None

    return (
        "The task ids are numbered wrong. They must run `T-001`, `T-002`, "
        "`T-003`, … — three digits, starting at 1, incrementing by exactly one "
        "with no gaps, and matching the order the tasks appear in the list:\n\n"
        + "\n".join(
            f"- task #{position} has id `{got}`; it must be `{want}`."
            for position, got, want in wrong
        )
        + "\n\nRenumber the tasks and return the complete plan again — the full "
        "design document markdown and the full task list."
    )


async def ask_user_questions(questions: Questions) -> str:
    """Prompt the user for answers to clarification questions.

    The questions are rendered as a tabbed, mouse-clickable prompt (see
    `QuestionsPrompt`); the answers come back as a JSON string suitable for
    feeding back to the agent as the next turn's prompt.
    """
    results = await QuestionsPrompt(questions).run()

    for result in results:
        rich.print(f"[green]✓[/] {result['Q']} [bold]→ {result['A']}[/]")
    if results:
        print()

    return json.dumps(results)
