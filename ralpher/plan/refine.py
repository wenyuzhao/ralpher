import tempfile
from pathlib import Path

from rich.console import Console

from ralpher.models import Project
from ralpher.utils.git import checkout_existing_branch

from ..utils.claude import ClaudeError, run_claude_plan_mode
from ..utils.error import fail

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

console = Console()


async def refine_plan(*, project: Project, prompt: str, model: str | None) -> str:
    """Run a Claude Code session to refine a Project Plan."""

    if not project.project_dir.exists():
        fail(f"{project.project_dir} does not exist.")

    if not (project.plan_md).exists():
        fail(f"{project.plan_md} does not exist.")

    # Checkout the project branch before refinement
    config = project.load_config()
    assert config is not None, "Project config should exist at this point."
    checkout_existing_branch(config.base_branch)

    with tempfile.NamedTemporaryFile(prefix="ralpher-refine-", suffix=".md") as tmp:
        tmp_path = Path(tmp.name)
        tmp_path.write_text(prompt)

        try:
            await run_claude_plan_mode(
                prompt=f"/ralpher:refine {project.id} {tmp_path}",
                project=project,
                model=model,
            )
        except ClaudeError as e:
            fail(f"Claude process exited with code {e.returncode}")

    if not (project.plan_md).exists():
        fail(f"{project.plan_md} was not created after refinement.")

    return project.id
