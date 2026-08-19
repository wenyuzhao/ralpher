import os
import tempfile
from pathlib import Path

import rich
from rich.console import Console

from ralpher.models import Project, Task
from ralpher.prompts import render_prompt
from ralpher.utils.git import checkout_existing_branch
from ralpher.utils.notion_comments import (
    fetch_plan_comments,
    render_comments_as_prompt,
    resolve_comments,
)

from ..backend import Plan, run_agent_plan_mode
from ..utils.error import fail

console = Console()

# Task fields a completed task must bring back unchanged. `id` is matched
# separately (it is the key), and `passed` is ralpher's own bookkeeping — the
# planning agent never sees or returns it.
_FROZEN_FIELDS = ("title", "description", "acceptance_criteria")


def check_completed_tasks(completed: list[Task], plan: Plan) -> str | None:
    """Error message if a refined plan changed an already-passing task, else None.

    A refine can land partway through a run, so the tasks that already passed
    are frozen: only the not-yet-passed ones may be re-planned. A completed task
    that comes back edited (or does not come back at all) either loses work
    already in the repo or gets implemented a second time — `save_planned_tasks`
    only carries `passed` across for an id that survived, so a renumbered task
    silently reverts to pending.

    The message is written as an instruction to the agent: `run_plan_mode` feeds
    it back as the next turn's prompt so the agent can fix its own output.
    """
    by_id = {task.id: task for task in plan.tasks}
    problems: list[str] = []
    for task in completed:
        planned = by_id.get(task.id)
        if planned is None:
            problems.append(f"- `{task.id}` ({task.title}) is missing from the list.")
            continue
        changed = [f for f in _FROZEN_FIELDS if getattr(planned, f) != getattr(task, f)]
        if changed:
            problems.append(
                f"- `{task.id}` ({task.title}) came back with a different "
                f"{', '.join(changed)}."
            )

    if not problems:
        return None

    return (
        "The task list you returned changed tasks that are already implemented "
        "and verified. Those tasks are frozen — each one must come back exactly "
        "as it appears in the original task list, with the same id, title, "
        "description, and acceptance criteria:\n\n"
        + "\n".join(problems)
        + "\n\nIf the refined design changes what one of those tasks built, "
        "leave the completed task untouched and add a NEW task, with a new "
        "unused id and placed after the completed ones, that adjusts or "
        "re-implements the affected code.\n\n"
        "Return the complete plan again — the full design document markdown and "
        "the full task list — with the completed tasks restored."
    )


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

        await run_agent_plan_mode(
            kind="refine",
            prompt=render_prompt(
                "refine",
                design_path=str(project.design_md),
                tasks_path=str(project.tasks_toml),
                input_path=str(tmp_path),
                jj=project.jj,
                completed_tasks=completed,
            ),
            project=project,
            validate=lambda plan: check_completed_tasks(completed, plan),
        )

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
