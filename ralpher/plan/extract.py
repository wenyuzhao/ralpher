import json
from pathlib import Path

import rich
from ..models import ProjectPlan, Project
from ..utils.claude import ClaudeError, run_claude
from ..utils.error import fail


async def __try_extract_plan(project: Project):
    """Run a Claude Code session to extract plan.json."""

    try:
        await run_claude(
            prompt=f"/ralpher:extract-plan {project.id}",
            project_dir=project.project_dir,
            model="haiku",
        )
    except ClaudeError as e:
        return False

    if not (project.plan_json).exists():
        return False
    try:
        project.load_plan()
    except Exception:
        return False
    return True


async def extract_plan_json(project: Project, retries: int = 3) -> None:
    """Run a Claude Code session to extract structured plan.json from PLAN.md."""

    if not project.project_dir.exists():
        fail(f"{project.project_dir} does not exist.")

    if not (project.plan_md).exists():
        fail(f"{project.plan_md} does not exist.")

    for i in range(retries):
        success = await __try_extract_plan(project)
        if success:
            return
        else:
            rich.print(
                f"[red]Failed to extract plan.json. Retrying... ({i+1}/{retries})[/]"
            )

    if not (project.plan_json).exists():
        fail(f"Failed to extract plan.json after {retries} attempts.")
