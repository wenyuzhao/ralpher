import rich
from rich.prompt import Confirm
from ralpher.models import Project, ProjectConfig
from ralpher.utils.error import fail
from ralpher.utils.git import (
    branch_exists,
    checkout_branch,
    resolve_default_base_branch,
)


def init_project_config(
    project: Project, base_branch: str | None, target_branch: str | None
) -> tuple[str, str]:
    # Validate branches and save config
    if base_branch is not None and not branch_exists(base_branch):
        fail(f"Base branch '{base_branch}' does not exist.")

    if target_branch and base_branch and branch_exists(target_branch):
        fail(
            f"Target branch '{target_branch}' already exists. "
            f"Remove --base-branch to use the existing branch, "
            f"or choose a different --target-branch."
        )

    if not base_branch:
        base_branch = resolve_default_base_branch()

    if not target_branch:
        target_branch = f"ralph/{project.id[18:]}"

    if branch_exists(target_branch):
        rich.print(
            f"[yellow][b]Warning:[/] Target branch [i]{target_branch}[/i] already exists and will be reused.[/]"
        )
        if not Confirm.ask("Do you want to continue?", default=True):
            raise SystemExit(0)

    project.project_dir.mkdir(parents=True, exist_ok=True)
    config = ProjectConfig(base_branch=base_branch, target_branch=target_branch)
    project.save_config(config)

    return target_branch, base_branch


def init_project(
    project: Project,
    prompt: str,
    base_branch: str | None = None,
    target_branch: str | None = None,
) -> None:
    """Initialize project directory and files for a new project."""
    target_branch, base_branch = init_project_config(
        project, base_branch, target_branch
    )

    # Create the target branch pointing at base_branch, then switch back
    checkout_branch(target_branch, base_branch)

    # Save the prompt to PROMPT.md
    project.prompt_md.write_text(prompt)
