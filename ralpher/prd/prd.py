import asyncio
import json
from pathlib import Path
import datetime

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts.choice_input import ChoiceInput
import rich
from rich.console import Console
from slugify import slugify


PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

console = Console()


def _parse_result(data: dict) -> tuple[list[dict] | None, str | None]:
    """Parse JSON output for AskUserQuestion tool calls.

    Returns (questions, session_id). questions is None if no AskUserQuestion found.
    """
    session_id = data.get("session_id")
    questions: list[dict] = []

    for pd in data.get("permission_denials", []):
        if pd.get("tool_name") == "AskUserQuestion":
            qs = pd.get("tool_input", {}).get("questions", [])
            questions.extend(qs)
            break

    return questions or None, session_id


async def _ask_user_questions(questions: list[dict]) -> str:
    """Prompt the user for answers to AskUserQuestion questions."""
    session = PromptSession()
    answers: list[str] = []

    rich.print(
        f"[bold on blue]Please answer the following questions to clarify the task:[/]"
    )

    for index, q in enumerate(questions):
        header = q.get("header", "")
        question_text = q.get("question", "")
        options = q.get("options", [])
        if not options:
            continue

        console.print()
        choice_options = [
            (
                opt.get("label", ""),
                f"{opt.get('label', '')} - {opt.get('description', '')}",
            )
            for opt in options
        ]
        choice_options.append(("__other__", HTML("Other - <style color='ansibrightblack'>[please specify]</style>"))) # type: ignore
        result = await ChoiceInput(
            message=HTML(
                f"<style color='ansimagenta'><b>[Q{index + 1}] <i>{header}:</i></b> {question_text}</style>"
            ),
            options=choice_options,
        ).prompt_async()
        if result == "__other__":
            answer = await session.prompt_async(
                HTML("<b><i>Enter your answer: </i></b>")
            )
        else:
            answer = result if result else choice_options[0][0]

        answers.append(f"{question_text}: {answer}")

    return "\n".join(answers)


async def generate_prd(user_input: str, name: str | None = None) -> str:
    """Run a Claude Code session with the rendered PRD prompt."""

    task_id = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    if name:
        task_id += f"-{slugify(name)}"
    task_dir = Path.cwd() / ".ralpher" / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "PROMPT.md").write_text(user_input)

    session_id: str | None = None
    current_prompt = f"/ralpher:prd {task_id}"

    while True:
        cmd = [
            "claude",
            "--output-format",
            "json",
            "--dangerously-skip-permissions",
            "--permission-mode",
            "dontAsk",
            "--plugin-dir",
            str(Path(__file__).resolve().parent.parent / "plugin"),
        ]
        if session_id:
            cmd += ["--resume", session_id]
        cmd += ["--print", current_prompt]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        await proc.wait()
        if proc.stdout:
            stdout_bytes = await proc.stdout.read()
        else:
            stdout_bytes = b""

        if proc.returncode != 0:
            console.print(
                f"[bold red]Claude process exited with code {proc.returncode}[/]"
            )
            raise SystemExit(proc.returncode)

        try:
            data = json.loads(stdout_bytes.decode())
        except json.JSONDecodeError:
            data = {}

        questions, new_session_id = _parse_result(data)
        if new_session_id:
            session_id = new_session_id

        if proc.returncode != 0 and not questions:
            raise RuntimeError(f"claude exited with code {proc.returncode}")

        if questions:
            current_prompt = await _ask_user_questions(questions)
        else:
            break

    if not (task_dir / "PRD.md").exists():
        console.print(f"[bold red]PRD.md not found in {task_dir}[/]")
        raise SystemExit(1)

    return task_id
