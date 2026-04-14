import tempfile
from pathlib import Path

from rich.console import Console

from ralpher.models import Project

from ..utils.claude import ClaudeError, run_claude
from ..utils.error import fail

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

console = Console()


async def refine_plan(*, project: Project, prompt: str, model: str | None) -> str:
    """Run a Claude Code session to refine a Project Plan."""

    if not project.project_dir.exists():
        fail(f"{project.project_dir} does not exist.")

    if not (project.plan_md).exists():
        fail(f"{project.plan_md} does not exist.")

    with tempfile.NamedTemporaryFile(prefix=f"ralpher-refine-", suffix=".md") as tmp:
        tmp_path = Path(tmp.name)
        tmp_path.write_text(prompt)

        try:
            await run_claude(
                prompt=f"/ralpher:refine-plan {project.id} {tmp_path}",
                project_dir=project.project_dir,
                interactive=True,
                model=model,
            )
        except ClaudeError as e:
            fail(f"Claude process exited with code {e.returncode}")

    if not (project.plan_md).exists():
        fail(f"{project.plan_md} was not created after refinement.")

    return project.id
