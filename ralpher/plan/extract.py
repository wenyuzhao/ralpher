import rich
from ..models import Project
from ..utils.claude import ClaudeError, run_claude
from ..utils.error import fail


async def __try_extract_tasks(project: Project):
    """Run a Claude Code session to extract tasks.json."""

    try:
        await run_claude(
            prompt=f"/ralpher:extract-tasks {project.id}",
            project_dir=project.project_dir,
            model="haiku",
        )
    except ClaudeError as e:
        return False

    if not (project.tasks_json).exists():
        return False
    try:
        tasks = project.load_tasks()
        assert tasks is not None
        # set passes to false
        for task in tasks.tasks:
            task.passes = False
        project.save_tasks(tasks)
    except Exception:
        return False
    return True


async def extract_tasks(project: Project, retries: int = 3) -> None:
    """Run a Claude Code session to extract structured tasks.json from PLAN.md."""

    if not project.project_dir.exists():
        fail(f"{project.project_dir} does not exist.")

    if not (project.plan_md).exists():
        fail(f"{project.plan_md} does not exist.")

    for i in range(retries):
        success = await __try_extract_tasks(project)
        if success:
            return
        else:
            rich.print(
                f"[red]Failed to extract tasks.json. Retrying... ({i+1}/{retries})[/]"
            )

    if not (project.tasks_json).exists():
        fail(f"Failed to extract tasks.json after {retries} attempts.")
