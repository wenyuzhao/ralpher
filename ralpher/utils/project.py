import subprocess

import rich
from rich.prompt import Confirm
from ralpher.models import Project


def init_project(project: Project, prompt: str) -> None:
    """Initialize project directory and files for a new project."""
    project.project_dir.mkdir(parents=True, exist_ok=True)

    # Save the prompt to a PROMPT.md
    project.prompt_md.write_text(prompt)

    # Check if branch already exists
    branches = (
        subprocess.check_output(
            ["git", "branch", "--list", project.branch], stderr=subprocess.DEVNULL
        )
        .decode()
        .strip()
    )
    if branches:
        rich.print(
            f"[yellow][b]Warning:[/] Branch [i]{project.branch}[/i] already exists and will be reused.[/]"
        )
        if not Confirm.ask("Do you want to continue?", default=True):
            # Delete the project directory if the user cancels
            subprocess.check_call(
                ["rm", "-rf", str(project.project_dir)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            raise SystemExit(0)
