import asyncio
import json
from pathlib import Path
from datetime import datetime
from typing import IO, Any, overload
import html

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts.choice_input import ChoiceInput
import rich
from pydantic import BaseModel

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


class ClaudeError(Exception):
    """Raised when the claude subprocess exits with a non-zero code."""

    def __init__(self, returncode: int):
        self.returncode = returncode
        super().__init__(f"Claude process exited with code {returncode}")


class Plan(BaseModel):
    markdown: str


class PlanOrQuestions(BaseModel):
    plan_or_questions: Questions | Plan


def _build_cmd(
    prompt: str,
    *,
    model: str | None = None,
    session_id: str | None = None,
    schema: dict[str, Any] | None = None,
    readonly: bool = False,
    tools: list[str] | None = None,
) -> list[str]:
    cmd = [
        "claude",
        "--permission-mode",
        "dontAsk",
        "--output-format",
        "stream-json",
        "--verbose",
        "--plugin-dir",
        PLUGIN_DIR,
    ]
    if model:
        cmd += ["--model", model]
    if session_id:
        cmd += ["--resume", session_id]
    if schema:
        cmd += ["--json-schema", json.dumps(schema)]
    if readonly:
        tools = tools or READONLY_TOOLS
    else:
        cmd += ["--dangerously-skip-permissions"]
    if tools is not None:
        cmd += ["--tools", ",".join(tools)]
        cmd += ["--allowed-tools", ",".join(tools)]
    cmd += ["--print", prompt]
    return cmd


async def _exec(cmd: list[str], logs: int | IO[Any]) -> int:
    """Execute claude subprocess with spinner, return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=logs, stderr=logs)
    async with Spinner() as spinner:
        await spinner.run(proc)
    assert proc.returncode is not None  # returncode should be set after process exits
    return proc.returncode


async def _ask_user_questions(questions: Questions) -> str:
    """Prompt the user for answers to AskUserQuestion questions."""
    session = PromptSession()
    answers: list[str] = []

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
                HTML("Other - <style color='ansibrightblack'>[please specify]</style>"),  # type: ignore
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
        answers.append(f"{q.question}: {answer}")

    print()
    return "\n".join(answers)


def _get_session_id(log: Path) -> str | None:
    try:
        jsonl = log.read_text()
        for line in jsonl.splitlines():
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            if "session_id" in data:
                return data["session_id"]
        return None
    except Exception:
        # print(f"Error occurred while fetching session ID: {e}")
        return None


def _load_structured_output(log: Path) -> Any:
    jsonl = log.read_text()
    for line in reversed(jsonl.splitlines()):
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        if record.get("type") == "result" and "structured_output" in record:
            return record["structured_output"]
    fail("Failed to get structured output from Claude.")


@overload
async def run_claude(
    *,
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
    prompt: str,
    project: Project,
    model: str | None = None,
    schema: type[T],
    readonly: bool = False,
    tools: list[str] | None = None,
) -> T: ...


async def run_claude[T: BaseModel](
    *,
    prompt: str,
    project: Project,
    model: str | None = None,
    schema: type[T] | None = None,
    readonly: bool = False,
    tools: list[str] | None = None,
) -> T | None:
    """
    Run the claude CLI subprocess.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    logs = project.project_dir / "logs" / f"claude-{timestamp}.log"
    if logs:
        logs.parent.mkdir(parents=True, exist_ok=True)

    with logs.open("ab") as f:
        json_s = json.dumps({"initial_prompt": prompt})
        f.write(f"{json_s}\n\n".encode())
        f.flush()

        schema_dict = schema.model_json_schema() if schema else None
        cmd = _build_cmd(
            prompt, model=model, schema=schema_dict, readonly=readonly, tools=tools
        )
        returncode = await _exec(cmd, logs=f)
        f.flush()
        if returncode != 0:
            raise ClaudeError(returncode)
    if schema:
        output_data = _load_structured_output(logs)
        return schema.model_validate(output_data)
    return None


async def run_claude_plan_mode(
    *, prompt: str, project: Project, model: str | None = None
):
    """Run claude in stream-json mode with Q&A loop."""

    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    logs = project.project_dir / "logs" / f"claude-{timestamp}.log"
    if logs:
        logs.parent.mkdir(parents=True, exist_ok=True)

    session_id: str | None = None
    current_prompt = prompt

    with logs.open("ab") as f:
        json_s = json.dumps({"initial_prompt": current_prompt})
        f.write(f"{json_s}\n\n".encode())
        f.flush()

        while True:
            schema = PlanOrQuestions.model_json_schema()
            cmd = _build_cmd(
                current_prompt,
                model=model,
                session_id=session_id,
                schema=schema,
                readonly=True,
            )
            returncode = await _exec(cmd, logs=f)
            f.flush()
            if returncode != 0:
                raise ClaudeError(returncode)

            # Get session id
            if not session_id:
                session_id = _get_session_id(logs)
            if not session_id:
                fail("Failed to get claude session ID.")

            # Parse structured output and ask user questions if needed
            output_data = _load_structured_output(logs)
            output = PlanOrQuestions.model_validate(output_data)

            # Process structured output
            assert output is not None
            if isinstance(output.plan_or_questions, Plan):
                project.plan_md.write_text(output.plan_or_questions.markdown)
                return
            else:
                current_prompt = await _ask_user_questions(output.plan_or_questions)
                json_s = json.dumps({"answers": current_prompt})
                f.write(f"\n{json_s}\n\n".encode())
                continue
