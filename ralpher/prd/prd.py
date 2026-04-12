import asyncio
import json
import shutil
from pathlib import Path
import datetime

import frontmatter
import jinja2
from rich.console import Console
from rich.prompt import Prompt


PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

console = Console()


def load_prd_prompt(user_input: str, *, interactive: bool = True) -> str:
    """Load the PRD template, strip frontmatter, and render with user input."""
    template_path = PROMPTS_DIR / "PRD.md"
    post = frontmatter.load(str(template_path))
    content = post.content
    template = jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(content)
    return template.render(prompt=user_input, interactive=interactive)


def _parse_result(data: dict) -> tuple[list[dict] | None, str | None]:
    """Parse JSON output for AskUserQuestion tool calls.

    Returns (questions, session_id). questions is None if no AskUserQuestion found.
    """
    session_id = data.get("session_id")
    questions: list[dict] | None = None

    for pd in data.get("permission_denials", []):
        if pd.get("tool_name") == "AskUserQuestion":
            questions = pd.get("tool_input", {}).get("questions", [])
            break

    return questions, session_id


def _ask_user_questions(questions: list[dict]) -> str:
    """Prompt the user for answers to AskUserQuestion questions using Rich."""
    answers: list[str] = []

    for index, q in enumerate(questions):
        header = q.get("header", "")
        question_text = q.get("question", "")
        options = q.get("options", [])

        console.print()
        if options:
            console.print(
                f"[on blue][b i]Q{index + 1}: {header}[/] - {question_text}[/]"
            )
            for i, opt in enumerate(options):
                label = opt.get("label", "")
                description = opt.get("description", "")
                console.print(
                    f"  [bold]{chr(65 + i)}.[/bold] [bold]{label}[/] [bright_black]-[/] [italic]{description}[/]"
                )
            console.print()
            answer = Prompt.ask("Your answer")
        else:
            answer = Prompt.ask(f"[cyan]{question_text}[/cyan]")

        answers.append(f"{question_text}: {answer}")

    return "\n".join(answers)


async def generate_prd(user_input: str) -> str:
    """Run a Claude Code session with the rendered PRD prompt."""

    task_id = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
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
        stdout_bytes = await proc.stdout.read()

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
            current_prompt = _ask_user_questions(questions)
        else:
            break

    if not (task_dir / "PRD.md").exists():
        console.print(f"[bold red]PRD.md not found in {task_dir}[/]")
        raise SystemExit(1)

    return task_id
