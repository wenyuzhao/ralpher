import subprocess
from pathlib import Path

import rich
from rich.prompt import Confirm


def init_project(task_dir: Path, prompt: str) -> None:
    """Initialize project directory and files for a new task."""
    task_dir.mkdir(parents=True, exist_ok=True)
    task_id = task_dir.name
    branch = f"ralph/{task_id[18:]}"

    # Save the prompt to a PROMPT.md
    (task_dir / "PROMPT.md").write_text(prompt)

    # Check if branch already exists
    branches = (
        subprocess.check_output(
            ["git", "branch", "--list", branch], stderr=subprocess.DEVNULL
        )
        .decode()
        .strip()
    )
    if branches:
        rich.print(
            f"[yellow][b]Warning:[/] Branch [i]{branch}[/i] already exists and will be reused.[/]"
        )
        if not Confirm.ask("Do you want to continue?", default=True):
            # Delete the task directory if the user cancels
            subprocess.check_call(
                ["rm", "-rf", str(task_dir)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            raise SystemExit(0)
