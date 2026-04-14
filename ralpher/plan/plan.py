from pathlib import Path

from ralpher.models import Project
from ralpher.utils.project import init_project

from ..utils.claude import ClaudeError, run_claude
from ..utils.error import fail


async def generate_plan(*, project: Project, prompt: str, model: str | None) -> str:
    """Run a Claude Code session to generate a Project Plan."""

    init_project(project, prompt)

    try:
        await run_claude(
            prompt=f"/ralpher:plan {project.id}",
            project_dir=project.project_dir,
            interactive=True,
            model=model,
        )
    except ClaudeError as e:
        fail(f"Claude process exited with code {e.returncode}")

    if not (project.plan_md).exists():
        fail(f"{project.plan_md} was not created.")

    return project.id
