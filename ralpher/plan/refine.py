import os
import tempfile
from pathlib import Path

import rich
from rich.console import Console

from ralpher.agents import Refiner
from ralpher.models import Project
from ralpher.utils.git import checkout_existing_branch
from ralpher.utils.notion_comments import (
    fetch_plan_comments,
    render_comments_as_prompt,
    resolve_comments,
)

from ..utils.error import fail

console = Console()


def _notion_configured() -> bool:
    return "RALPHER_NOTION_TOKEN" in os.environ and (
        "RALPHER_NOTION_PAGE_ID" in os.environ
        or "RALPHER_NOTION_PARENT_PAGE_ID" in os.environ
    )


async def refine_plan(*, project: Project, prompt: str | None) -> str | None:
    """Run a coding-agent session to refine design.md and tasks.toml.

    `prompt` is the user-supplied refinement instruction. If Notion is
    configured (see `_notion_configured`), any unresolved comments under the
    `📐 Design` and `📋 Task List` sections of the project's Notion page are
    appended to the prompt and then marked resolved after refinement.

    Returns the project id when refinement runs, or None when there is
    nothing to refine (empty prompt and no Notion comments).
    """

    if not project.project_dir.exists():
        fail(f"{project.project_dir} does not exist.")

    if not (project.design_md).exists():
        fail(f"{project.design_md} does not exist.")

    comments = []
    if _notion_configured():
        comments = await fetch_plan_comments(project)
        if comments:
            rich.print(
                f"[bold blue]Found {len(comments)} Notion comment(s) on the Design and Task List sections.[/]\n"
            )

    combined = _combine_prompt(prompt, comments)
    if not combined:
        rich.print("[yellow]Nothing to refine. Skipping.[/]")
        return None

    # Tasks that already passed are off limits to this refinement: the agent is
    # told to return them verbatim, and the plan is rejected if it doesn't.
    tasks = project.load_tasks()
    completed = [t for t in tasks.tasks if t.passed] if tasks else []
    if completed:
        rich.print(
            f"[bold blue]{len(completed)} task(s) already completed; "
            "refining only the remaining work.[/]\n"
        )

    # Checkout the project branch before refinement
    config = project.load_config()
    assert config is not None, "Project config should exist at this point."
    checkout_existing_branch(config.base_branch)

    with tempfile.NamedTemporaryFile(prefix="ralpher-refine-", suffix=".md") as tmp:
        tmp_path = Path(tmp.name)
        tmp_path.write_text(combined)

        await Refiner(project, input_path=tmp_path, completed=completed).run()

    if not (project.design_md).exists():
        fail(f"{project.design_md} was not created after refinement.")

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
