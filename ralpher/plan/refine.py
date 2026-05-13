import tempfile
from pathlib import Path

import rich
from rich.console import Console

from ralpher.models import Project
from ralpher.utils.git import checkout_existing_branch
from ralpher.utils.notion_comments import (
    fetch_project_plan_comments,
    render_comments_as_prompt,
    resolve_comments,
)

from ..utils.claude import run_claude_plan_mode
from ..utils.error import fail

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

console = Console()


async def refine_plan_from_notion(*, project: Project, model: str | None) -> str:
    """Refine the Project Plan using comments from the project's Notion page.

    Pulls every block-level comment under the `📜 Project Plan` heading,
    formats them into a refinement prompt, runs the normal refine flow, then
    marks those comments resolved on the Notion side.
    """
    comments = await fetch_project_plan_comments(project)
    if not comments:
        fail(
            "No Notion comments found on the Project Plan section. "
            "Make sure RALPHER_NOTION_TOKEN and RALPHER_NOTION_PAGE_ID "
            "(or RALPHER_NOTION_PARENT_PAGE_ID) are set and the page has unresolved comments."
        )

    rich.print(
        f"[bold blue]Found {len(comments)} Notion comment(s) on the Project Plan section.[/]\n"
    )
    prompt = render_comments_as_prompt(comments)
    result = await refine_plan(project=project, prompt=prompt, model=model)
    rich.print(f"[bold blue]Resolving {len(comments)} Notion comment(s)…[/]")
    await resolve_comments(comments)
    return result


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

        await run_claude_plan_mode(
            prompt=f"/ralpher:refine {project.id} {tmp_path}",
            project=project,
            model=model,
        )

    if not (project.plan_md).exists():
        fail(f"{project.plan_md} was not created after refinement.")

    return project.id
