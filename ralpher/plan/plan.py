from ralpher.models import Project
from ralpher.prompts import render_prompt
from ralpher.utils.project import init_project

from ..backend import run_agent_plan_mode
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

    await run_agent_plan_mode(
        kind="plan",
        prompt=render_prompt("plan", prompt_path=str(project.prompt_md), jj=project.jj),
        project=project,
    )

    if not (project.design_md).exists():
        fail(f"{project.design_md} was not created.")
    if not (project.tasks_toml).exists():
        fail(f"{project.tasks_toml} was not created.")

    return project.id
