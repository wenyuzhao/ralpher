"""Backend-agnostic plan-mode pieces shared by every agent backend.

The plan-mode output schema (`Plan` / `PlanOrQuestions`) and the interactive
clarification-question UX (`ask_user_questions`) don't depend on which agent
SDK produced them, so they live here rather than in any one backend. This lets
the claude-code and antigravity backends stay independent of each other.
"""

import json

import rich
from pydantic import BaseModel, Field

from ralpher.models import PlannedTask, Questions
from ralpher.utils.questions_ui import QuestionsPrompt


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
