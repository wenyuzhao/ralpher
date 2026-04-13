import asyncio
import json
from pathlib import Path
from typing import IO, Any, Literal, overload

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts.choice_input import ChoiceInput
import rich
from asyncio.subprocess import DEVNULL, PIPE

from .spinner import Spinner


PLUGIN_DIR = str(Path(__file__).resolve().parent.parent / "plugin")


class ClaudeError(Exception):
    """Raised when the claude subprocess exits with a non-zero code."""

    def __init__(self, returncode: int, stdout: bytes = b"", stderr: bytes = b""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(f"Claude process exited with code {returncode}")


def _build_cmd(
    prompt: str,
    *,
    json_output: bool = False,
    model: str | None = None,
    session_id: str | None = None,
) -> list[str]:
    cmd = [
        "claude",
        "--dangerously-skip-permissions",
        "--permission-mode",
        "dontAsk",
        "--plugin-dir",
        PLUGIN_DIR,
    ]
    if json_output:
        cmd += ["--output-format", "json"]
    if model:
        cmd += ["--model", model]
    if session_id:
        cmd += ["--resume", session_id]
    cmd += ["--print", prompt]
    return cmd


async def _exec(
    cmd: list[str], stdout: int | IO[Any], stderr: int | IO[Any]
) -> tuple[int, bytes | None, bytes | None]:
    """Execute claude subprocess with spinner, return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=stdout, stderr=stderr)
    async with Spinner() as spinner:
        await spinner.run(proc)
    out = await proc.stdout.read() if proc.stdout else None
    err = await proc.stderr.read() if proc.stderr else None
    assert proc.returncode is not None  # returncode should be set after process exits
    return proc.returncode, out, err


def _parse_questions(data: dict) -> tuple[list[dict] | None, str | None]:
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
        "[bold blue]Please answer the following questions to clarify the task:[/]"
    )

    for index, q in enumerate(questions):
        question_text = q.get("question", "")
        options = q.get("options", [])
        if not options:
            continue

        print()
        header = q.get("header", "")
        choice_options = [
            (
                opt.get("label", ""),
                f"{opt.get('label', '')} - {opt.get('description', '')}",
            )
            for opt in options
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

    print()
    return "\n".join(answers)


async def run_claude(
    prompt: str,
    *,
    mode: Literal["qa", "text"] = "text",
    model: str | None = None,
    logs: tuple[Path, Path] | None = None,
) -> dict | None:
    """Run the claude CLI subprocess.

    In qa mode: runs with --output-format json and handles AskUserQuestion
    loop automatically. Returns the final parsed JSON dict.

    In text mode: pipes output to log files if logs=(stdout_path, stderr_path)
    is provided, otherwise discards output.

    Raises ClaudeError on non-zero exit codes (in text mode, or in qa mode
    when no questions are pending).
    """
    if mode == "qa":
        return await _run_json_looped(prompt, model=model)
    else:
        await _run_text(prompt, model=model, logs=logs)
        return None


async def _run_json_looped(prompt: str, *, model: str | None = None) -> dict:
    """Run claude in JSON mode with Q&A loop."""
    session_id: str | None = None
    current_prompt = prompt

    while True:
        cmd = _build_cmd(
            current_prompt, json_output=True, model=model, session_id=session_id
        )
        returncode, stdout, stderr = await _exec(cmd, stdout=PIPE, stderr=PIPE)
        assert stdout is not None and stderr is not None

        try:
            data = json.loads(stdout.decode())
        except json.JSONDecodeError:
            data = {}

        questions, new_session_id = _parse_questions(data)
        if new_session_id:
            session_id = new_session_id

        if returncode != 0 and not questions:
            raise ClaudeError(returncode, stdout, stderr)

        if questions:
            current_prompt = await _ask_user_questions(questions)
        else:
            return data


async def _run_text(
    prompt: str,
    *,
    model: str | None = None,
    logs: tuple[Path, Path] | None = None,
) -> None:
    """Run claude in text mode, redirecting output to files or DEVNULL."""
    cmd = _build_cmd(prompt, model=model)
    if logs:
        with open(logs[0], "wb") as stdout_file, open(logs[1], "wb") as stderr_file:
            returncode, _, _ = await _exec(cmd, stdout=stdout_file, stderr=stderr_file)
    else:
        returncode, _, _ = await _exec(cmd, stdout=DEVNULL, stderr=DEVNULL)

    if returncode != 0:
        raise ClaudeError(returncode)
