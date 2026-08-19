"""Backend-agnostic plan-mode pieces shared by every agent backend.

The plan-mode output schema (`Plan` / `PlanOrQuestions`) and the interactive
clarification-question UX (`ask_user_questions`) don't depend on which agent
SDK produced them, so they live here rather than in any one backend. This lets
the claude-code and antigravity backends stay independent of each other.
"""

import json

import rich
from pydantic import BaseModel, Field

from ralpher.models import Questions
from ralpher.utils.questions_ui import QuestionsPrompt


class Plan(BaseModel):
    """Returned when the Project Plan is complete and ready."""

    markdown: str = Field(
        description="The complete markdown content of the Project Plan. DO NOT provide a summary or file path -- you MUST return the full markdown text of the plan here."
    )


class PlanOrQuestions(BaseModel):
    """Root structured output for plan mode."""

    plan_or_questions: Questions | Plan = Field(
        description="Must be either a Questions object (with a 'questions' list) if clarification is needed, or a Plan object (with a 'markdown' containing the full markdown text of the Project Plan)."
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
