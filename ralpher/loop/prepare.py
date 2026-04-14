from datetime import datetime
from pathlib import Path
import sys

import rich
from rich.prompt import Confirm

from ralpher.models import Project
from ralpher.utils.error import fail
from ralpher.utils.git import checkout_branch
from ralpher.utils.hooks.hooks import HooksManager
from ..plan.extract import extract_plan_json


async def prepare(project: Project, hooks: HooksManager) -> bool:
    # Check if PLAN.md exists
    if not project.plan_md.exists():
        await hooks.on_error("PLAN.md not found")
        fail(f"{project.plan_md} not found.")

    # Extract plan.json from PLAN.md if it doesn't exist
    if not project.plan_json.exists():
        rich.print(f"[bold blue]Extracting plan.json from PLAN.md[/]\n")
        await hooks.on_extract_start()
        try:
            await extract_plan_json(project)
        except Exception as e:
            await hooks.on_error(f"Failed to extract plan.json: {str(e)}")
            fail(f"Failed to extract plan.json: {str(e)}")
        if not project.plan_json.exists():
            await hooks.on_error("Failed to extract plan.json")
            fail(f"{project.plan_json} still not found after extraction.")
        await hooks.on_extract_end()

    # Create logs directory
    logs_dir = project.project_dir / "logs"
    logs_dir.mkdir(exist_ok=True)

    # Load plan and check tasks
    plan = project.load_plan()
    assert plan is not None

    # Check if all tasks already pass
    num_tasks = len(plan.tasks)
    num_failed_tasks = len(plan.failed_tasks())
    if num_failed_tasks == 0:
        rich.print(f"[bold green]✔ All {num_tasks} tasks already pass![/]")
        await hooks.on_loop_end(0, True)
        return False

    # Check if max_iterations is less than number of tasks
    if project.max_iterations is not None and project.max_iterations < len(plan.tasks):
        rich.print(
            f"[yellow][b]Warning:[/] Max iterations ({project.max_iterations}) is less than the number of tasks ({len(plan.tasks)}). Some tasks may not be attempted.[/]\n"
        )
        if not Confirm.ask("Do you want to continue?", default=False):
            await hooks.on_cancel(
                "User aborted due to max_iterations < number of tasks."
            )
            sys.exit(0)

    # Report important info before starting the loop
    config = project.load_config()
    assert config is not None
    rich.print(f" • Incomplete tasks: {num_failed_tasks} / {num_tasks}")
    rich.print(f" • Branch: [i]{config.target_branch}[/]")
    rich.print(
        f" • Max iterations: {project.max_iterations if project.max_iterations is not None else 'Unlimited'}"
    )
    hooks.report_status()
    print()

    # Initialize progress file if it doesn't exist
    if not project.progress_md.exists():
        _init_progress(project.progress_md)

    # Track target branch
    checkout_branch(config.target_branch, config.base_branch)

    return True


def _init_progress(progress_file: Path) -> None:
    """Create or reset the progress file."""
    progress_file.write_text(
        f"# Ralph Progress Log\n**Started:** {datetime.now()}\n\n---\n\n"
    )


def finalize_progress(progress_file: Path) -> None:
    """Create or reset the progress file."""
    content = progress_file.read_text().strip()
    if not content.endswith("---"):
        content += "\n\n---"
    content += f"\n\n**Finished:** {datetime.now()}\n"
    progress_file.write_text(content)
