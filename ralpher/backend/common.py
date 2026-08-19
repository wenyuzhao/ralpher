"""Backend-agnostic plan-mode pieces shared by every agent backend.

The plan-mode output schema (`Plan` / `PlanOrQuestions`) and the interactive
clarification-question UX (`ask_user_questions`) don't depend on which agent
SDK produced them, so they live here rather than in any one backend. This lets
the claude-code and antigravity backends stay independent of each other.
"""

import html
import json

import rich
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML, AnyFormattedText
from prompt_toolkit.shortcuts.choice_input import ChoiceInput
from pydantic import BaseModel, Field

from ralpher.models import Questions


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

    Returns the answers as a JSON string suitable for feeding back to the
    agent as the next turn's prompt.
    """
    session = PromptSession()

    while True:
        results: list[dict[str, str]] = []

        rich.print("[bold blue]Please answer the following clarification questions:[/]")

        for index, q in enumerate(questions.questions):
            if not q.options:
                continue

            print()
            header = q.header
            choice_options: list[tuple[str, AnyFormattedText]] = [
                (opt.label, f"{opt.label} - {opt.description}") for opt in q.options
            ]
            choice_options.append(
                (
                    "__other__",
                    HTML(
                        "Other - <style color='ansibrightblack'>[please specify]</style>"
                    ),
                )
            )
            result = await ChoiceInput(
                message=HTML(
                    f"<style color='ansimagenta'><b>[Q{index + 1}] <i>{html.escape(header)}:</i></b> {html.escape(q.question)}</style>"
                ),
                options=choice_options,
            ).prompt_async()
            if result == "__other__":
                answer = await session.prompt_async(
                    HTML("<b><i>Enter your answer: </i></b>")
                )
            else:
                answer = result if result else choice_options[0][0]
            results.append({"Q": q.question, "A": answer})

        print()

        confirmed = await ChoiceInput(
            message=HTML(
                "<style color='ansiblue'><b>Submit these answers?</b></style>"
            ),
            options=[
                ("yes", "Yes - submit these answers"),
                ("no", "No - answer the questions again"),
            ],
        ).prompt_async()
        if confirmed == "yes":
            print()
            return json.dumps(results)
        print()
