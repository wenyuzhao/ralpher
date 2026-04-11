import asyncio
import json
import shutil
from pathlib import Path

import frontmatter
import jinja2
from rich.console import Console
from rich.panel import Panel
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

    for q in questions:
        question_text = q.get("question", "")
        options = q.get("options", [])

        console.print()
        if options:
            console.print(Panel(question_text, border_style="cyan"))
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


async def generate_prd(user_input: str, interactive=True) -> int:
    """Run a Claude Code session with the rendered PRD prompt.

    When interactive=True, intercepts AskUserQuestion tool calls from the
    JSON output, prompts the user via Rich, and resumes the session
    with their answers.
    """
    prompt = load_prd_prompt(user_input, interactive=interactive)

    claude_bin = shutil.which("claude")
    if claude_bin is None:
        raise RuntimeError("claude CLI not found on PATH")

    session_id: str | None = None
    current_prompt = prompt

    while True:
        cmd = [claude_bin, "--output-format", "json", "--dangerously-skip-permissions"]
        if session_id:
            cmd += ["--resume", session_id]
        cmd += ["--print", current_prompt]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout_bytes = await proc.stdout.read()
        await proc.wait()

        try:
            data = json.loads(stdout_bytes.decode())
        except json.JSONDecodeError:
            data = {}

        print("data", data)
        questions, new_session_id = _parse_result(data)
        print("questions", questions)
        if new_session_id:
            session_id = new_session_id

        if proc.returncode != 0 and not questions:
            print((await proc.stderr.read()).decode())
            print(stdout_bytes.decode())
            raise RuntimeError(f"claude exited with code {proc.returncode}")

        if questions and interactive:
            current_prompt = _ask_user_questions(questions)
        else:
            break

    return 0
