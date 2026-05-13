import dataclasses
import json
from pathlib import Path
from datetime import datetime
from typing import Any, overload
import html

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts.choice_input import ChoiceInput
import rich
from pydantic import BaseModel

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ResultMessage,
    query,
)

from ralpher.models import Project, Questions
from ralpher.utils.error import fail

from .spinner import Spinner


PLUGIN_DIR = str(Path(__file__).resolve().parent.parent / "plugin")

READONLY_TOOLS = [
    "Agent",
    "CronCreate",
    "CronDelete",
    "CronList",
    "Glob",
    "Grep",
    "ListMcpResourcesTool",
    "LSP",
    "Read",
    "ReadMcpResourceTool",
    "SendMessage",
    "TaskCreate",
    "TaskGet",
    "TaskList",
    "TaskOutput",
    "TaskStop",
    "TaskUpdate",
    "TeamCreate",
    "TeamDelete",
    "TodoWrite",
    "ToolSearch",
    "WebFetch",
    "WebSearch",
]


class Plan(BaseModel):
    markdown: str


class PlanOrQuestions(BaseModel):
    plan_or_questions: Questions | Plan


def _build_options(
    *,
    model: str | None = None,
    session_id: str | None = None,
    schema: dict[str, Any] | None = None,
    readonly: bool = False,
    tools: list[str] | None = None,
) -> ClaudeAgentOptions:
    if readonly:
        tools = tools or READONLY_TOOLS

    options = ClaudeAgentOptions(
        permission_mode="dontAsk" if readonly else "bypassPermissions",
        plugins=[{"type": "local", "path": PLUGIN_DIR}],
        model=model,
        resume=session_id,
        output_format={"type": "json_schema", "schema": schema} if schema else None,
        allowed_tools=tools if tools is not None else [],
        tools=(
            tools if tools is not None else {"type": "preset", "preset": "claude_code"}
        ),
    )
    return options


async def _run_query(
    prompt: str, options: ClaudeAgentOptions, log_file: Path
) -> ResultMessage:
    """Run a claude SDK query, stream messages to log, return the ResultMessage."""
    result: ResultMessage | None = None

    async with Spinner():
        async for message in query(prompt=prompt, options=options):
            # Log each message as JSONL
            with log_file.open("a") as f:
                try:
                    f.write(json.dumps(dataclasses.asdict(message)) + "\n")
                except Exception:
                    pass

            if isinstance(message, ResultMessage):
                result = message

    if result is None:
        fail("No result received from Claude.")

    if result.is_error:
        fail("Claude process returned an error.")

    return result


async def _ask_user_questions(questions: Questions) -> str:
    """Prompt the user for answers to AskUserQuestion questions."""
    session = PromptSession()

    while True:
        results: list[dict[str, str]] = []

        rich.print("[bold blue]Please answer the following clarification questions:[/]")

        for index, q in enumerate(questions.questions):
            if not q.options:
                continue

            print()
            header = q.header
            choice_options = [
                (opt.label, f"{opt.label} - {opt.description}") for opt in q.options
            ]
            choice_options.append(
                (
                    "__other__",
                    HTML(
                        "Other - <style color='ansibrightblack'>[please specify]</style>"
                    ),  # type: ignore
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


@overload
async def run_claude(
    *,
    kind: str,
    prompt: str,
    project: Project,
    model: str | None = None,
    schema: None = None,
    readonly: bool = False,
    tools: list[str] | None = None,
) -> None: ...


@overload
async def run_claude[T: BaseModel](
    *,
    kind: str,
    prompt: str,
    project: Project,
    model: str | None = None,
    schema: type[T],
    readonly: bool = False,
    tools: list[str] | None = None,
) -> T: ...


async def run_claude[T: BaseModel](
    *,
    kind: str,
    prompt: str,
    project: Project,
    model: str | None = None,
    schema: type[T] | None = None,
    readonly: bool = False,
    tools: list[str] | None = None,
) -> T | None:
    """
    Run the claude SDK to execute a prompt.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    log_file = project.project_dir / "logs" / f"{kind}-{timestamp}.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # Log initial prompt
    with log_file.open("w") as f:
        f.write(json.dumps({"initial_prompt": prompt}) + "\n\n")

    schema_dict = schema.model_json_schema() if schema else None
    options = _build_options(
        model=model, schema=schema_dict, readonly=readonly, tools=tools
    )

    result = await _run_query(prompt, options, log_file)

    if schema:
        if result.structured_output is None:
            fail("Failed to get structured output from Claude.")
        return schema.model_validate(result.structured_output)
    return None


async def run_claude_plan_mode(
    *, kind: str, prompt: str, project: Project, model: str | None = None
):
    """Run claude SDK with Q&A loop for plan generation."""

    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    log_file = project.project_dir / "logs" / f"{kind}-{timestamp}.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # Log initial prompt
    with log_file.open("w") as f:
        f.write(json.dumps({"initial_prompt": prompt}) + "\n\n")

    session_id: str | None = None
    current_prompt = prompt

    while True:
        schema = PlanOrQuestions.model_json_schema()
        options = _build_options(
            model=model,
            session_id=session_id,
            schema=schema,
            readonly=True,
        )

        result = await _run_query(current_prompt, options, log_file)

        # Capture session_id for resumption
        if not session_id:
            session_id = result.session_id

        # Parse structured output
        if result.structured_output is None:
            fail("Failed to get structured output from Claude.")

        output = PlanOrQuestions.model_validate(result.structured_output)

        if isinstance(output.plan_or_questions, Plan):
            project.plan_md.write_text(output.plan_or_questions.markdown)
            return
        else:
            current_prompt = await _ask_user_questions(output.plan_or_questions)
            with log_file.open("a") as f:
                f.write("\n" + json.dumps({"answers": current_prompt}) + "\n\n")
            continue
