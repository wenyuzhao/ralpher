from ralpher.agents import Planner
from ralpher.models import Project
from ralpher.utils.project import init_project

from ..utils.error import fail


async def generate_plan(
    *,
    project: Project,
    prompt: str,
    base_branch: str | None = None,
    target_branch: str | None = None,
) -> str:
    """Run a coding-agent session to generate design.md and tasks.toml."""

    init_project(project, prompt, base_branch=base_branch, target_branch=target_branch)

    await Planner(project).run()

    if not (project.design_md).exists():
        fail(f"{project.design_md} was not created.")
    if not (project.tasks_toml).exists():
        fail(f"{project.tasks_toml} was not created.")

    return project.id
