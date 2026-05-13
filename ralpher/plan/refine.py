import os
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


def _notion_configured() -> bool:
    return "RALPHER_NOTION_TOKEN" in os.environ and (
        "RALPHER_NOTION_PAGE_ID" in os.environ
        or "RALPHER_NOTION_PARENT_PAGE_ID" in os.environ
    )


async def refine_plan(
    *, project: Project, prompt: str | None, model: str | None
) -> str | None:
    """Run a Claude Code session to refine a Project Plan.

    `prompt` is the user-supplied refinement instruction. If Notion is
    configured (see `_notion_configured`), any unresolved comments under the
    `📜 Project Plan` section of the project's Notion page are appended to
    the prompt and then marked resolved after refinement.

    Returns the project id when refinement runs, or None when there is
    nothing to refine (empty prompt and no Notion comments).
    """

    if not project.project_dir.exists():
        fail(f"{project.project_dir} does not exist.")

    if not (project.plan_md).exists():
        fail(f"{project.plan_md} does not exist.")

    comments = []
    if _notion_configured():
        comments = await fetch_project_plan_comments(project)
        if comments:
            rich.print(
                f"[bold blue]Found {len(comments)} Notion comment(s) on the Project Plan section.[/]\n"
            )

    combined = _combine_prompt(prompt, comments)
    if not combined:
        rich.print("[yellow]Nothing to refine. Skipping.[/]")
        return None

    # Checkout the project branch before refinement
    config = project.load_config()
    assert config is not None, "Project config should exist at this point."
    checkout_existing_branch(config.base_branch)

    with tempfile.NamedTemporaryFile(prefix="ralpher-refine-", suffix=".md") as tmp:
        tmp_path = Path(tmp.name)
        tmp_path.write_text(combined)

        await run_claude_plan_mode(
            kind="refine",
            prompt=f"/ralpher:refine {project.id} {tmp_path}",
            project=project,
            model=model,
        )

    if not (project.plan_md).exists():
        fail(f"{project.plan_md} was not created after refinement.")

    if comments:
        rich.print(f"[bold blue]Resolving {len(comments)} Notion comment(s)…[/]")
        await resolve_comments(comments)

    return project.id


def _combine_prompt(prompt: str | None, comments: list) -> str:
    parts: list[str] = []
    if prompt and prompt.strip():
        parts.append(prompt.strip())
    if comments:
        parts.append(render_comments_as_prompt(comments))
    return "\n\n".join(parts)
