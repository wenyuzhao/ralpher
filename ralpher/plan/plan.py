from ralpher.models import Project
from ralpher.utils.project import init_project

from ..utils.claude import run_claude_plan_mode
from ..utils.error import fail


async def generate_plan(
    *,
    project: Project,
    prompt: str,
    base_branch: str | None = None,
    target_branch: str | None = None,
) -> str:
    """Run a Claude Code session to generate a Project Plan."""

    init_project(project, prompt, base_branch=base_branch, target_branch=target_branch)

    await run_claude_plan_mode(
        kind="plan",
        prompt=f"/ralpher:plan {project.id}",
        project=project,
    )

    if not (project.plan_md).exists():
        fail(f"{project.plan_md} was not created.")

    return project.id
