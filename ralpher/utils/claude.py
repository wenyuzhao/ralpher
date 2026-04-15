import asyncio
import json
import os
from pathlib import Path
from datetime import datetime
from typing import IO, Any
import html

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts.choice_input import ChoiceInput
import rich

from ralpher.models import Questions
from ralpher.utils.error import fail

from .spinner import Spinner


PLUGIN_DIR = str(Path(__file__).resolve().parent.parent / "plugin")


class ClaudeError(Exception):
    """Raised when the claude subprocess exits with a non-zero code."""

    def __init__(self, returncode: int):
        self.returncode = returncode
        super().__init__(f"Claude process exited with code {returncode}")


def _build_cmd(
    prompt: str,
    *,
    model: str | None = None,
    session_id: str | None = None,
) -> list[str]:
    cmd = [
        "claude",
        "--dangerously-skip-permissions",
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
    except Exception as e:
        # print(f"Error occurred while fetching session ID: {e}")
        return None


async def run_claude(
    *,
    prompt: str,
    project_dir: Path,
    interactive: bool = False,
    model: str | None = None,
):
    """
    Run the claude CLI subprocess.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    logs = project_dir / "logs" / f"claude-{timestamp}.log"
    if logs:
        logs.parent.mkdir(parents=True, exist_ok=True)
    await _run_claude_looped(
        project_dir=project_dir,
        prompt=prompt,
        logs=logs,
        model=model,
        interactive=interactive,
    )


async def _run_claude_looped(
    *,
    project_dir: Path,
    prompt: str,
    logs: Path,
    model: str | None,
    interactive: bool,
):
    """Run claude in JSON mode with Q&A loop."""
    session_id: str | None = None
    current_prompt = prompt

    with logs.open("ab") as f:
        json_s = json.dumps({"initial_prompt": current_prompt})
        f.write(f"{json_s}\n\n".encode())
        f.flush()

        while True:
            Questions.clear(project_dir)

            cmd = _build_cmd(current_prompt, model=model, session_id=session_id)
            returncode = await _exec(cmd, logs=f)
            f.flush()
            if returncode != 0:
                raise ClaudeError(returncode)

            if interactive:
                # Get session id
                session_id = _get_session_id(logs)
                if not session_id:
                    fail("Failed to get claude session ID.")

                try:
                    questions = Questions.load(project_dir)
                except Exception:
                    current_prompt = "Invalid JSON output. Please fix the JSON formatting errors and try again."
                    continue

                if questions and questions.questions:
                    current_prompt = await _ask_user_questions(questions)
                    json_s = json.dumps({"answers": current_prompt})
                    f.write(f"\n{json_s}\n\n".encode())
                    f.flush()
                    continue

            break
