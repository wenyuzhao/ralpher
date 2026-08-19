import sys
from datetime import datetime
from pathlib import Path

import rich
from rich.prompt import Confirm

from ralpher.models import Project
from ralpher.utils.error import fail
from ralpher.utils.git import checkout_branch
from ralpher.utils.hooks.hooks import HooksManager


async def prepare(project: Project, hooks: HooksManager) -> bool:
    # Both halves of the plan come out of `ralpher plan` together, so a missing
    # one means planning never ran (or was interrupted) rather than something
    # the loop can recover from.
    if not project.design_md.exists():
        fail(f"{project.design_md} not found. Run 'ralpher plan' first.")

    if not project.tasks_toml.exists():
        fail(f"{project.tasks_toml} not found. Run 'ralpher plan' first.")

    # Create logs directory
    logs_dir = project.project_dir / "logs"
    logs_dir.mkdir(exist_ok=True)

    # Load and check tasks
    tasks = project.load_tasks()
    assert tasks is not None

    # Check if max_iterations is less than number of tasks
    if project.max_iterations is not None and project.max_iterations < len(tasks.tasks):
        rich.print(
            f"[yellow][b]Warning:[/] Max iterations ({project.max_iterations}) is less than the number of tasks ({len(tasks.tasks)}). Some tasks may not be attempted.[/]\n"
        )
        if not Confirm.ask("Do you want to continue?", default=False):
            await hooks.on_cancel(
                "User aborted due to max_iterations < number of tasks."
            )
            sys.exit(0)

    # Report important info before starting the loop
    num_tasks = len(tasks.tasks)
    num_failed_tasks = len(tasks.failed_tasks())
    config = project.load_config()
    assert config is not None
    rich.print(f" • Incomplete tasks: {num_failed_tasks} / {num_tasks}")
    rich.print(f" • Branch: [i]{config.target_branch}[/]")
    rich.print(
        f" • Max iterations: {project.max_iterations if project.max_iterations is not None else 'Unlimited'}"
    )
    hooks.report_status()
    print()

    # Check if all tasks already pass
    if num_failed_tasks == 0:
        rich.print(f"[bold green]✔ All {num_tasks} tasks already pass![/]")
        await hooks.on_loop_end(0, True)
        return False

    # Initialize progress file if it doesn't exist
    if not project.progress_md.exists():
        _init_progress(project.progress_md)

    # Track target branch
    checkout_branch(config.target_branch, config.base_branch)

    return True


def _init_progress(progress_file: Path) -> None:
    """Create or reset the progress file."""
    progress_file.write_text(
        f"# Ralph Progress Log\n\n**Started:** {datetime.now().astimezone()}\n\n---\n\n"
    )


def finalize_progress(progress_file: Path) -> None:
    """Create or reset the progress file."""
    content = progress_file.read_text().strip()
    if not content.endswith("---"):
        content += "\n\n---"
    content += f"\n\n**Finished:** {datetime.now().astimezone()}\n"
    progress_file.write_text(content)
