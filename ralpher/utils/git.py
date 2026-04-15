from pathlib import Path
import subprocess
from subprocess import DEVNULL

from ralpher.utils.error import fail


def get_current_branch() -> str | None:
    """Return the current branch name, or None if HEAD doesn't exist."""
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], stderr=DEVNULL
            )
            .decode()
            .strip()
        )
    except subprocess.CalledProcessError:
        return None


def branch_exists(branch: str) -> bool:
    """Check whether a local branch exists."""
    result = (
        subprocess.check_output(["git", "branch", "--list", branch], stderr=DEVNULL)
        .decode()
        .strip()
    )
    return bool(result)


def _check_empty_git_history() -> None:
    """Check if the git repository has any commits."""
    current = get_current_branch()

    if not current:
        fail(
            "No git history found. Please create the [i]main[/] branch with an initial commit before running ralpher."
        )


def _is_in_git_repo() -> bool:
    """Check whether CWD is inside a git repository."""
    try:
        subprocess.check_output(
            ["git", "rev-parse", "--is-inside-work-tree"], stderr=DEVNULL
        )
        return True
    except subprocess.CalledProcessError:
        return False


def _init_repo() -> None:
    """Initialize a new git repo with an empty commit on main."""
    subprocess.check_call(["git", "init", "-b", "main"], stderr=DEVNULL, stdout=DEVNULL)
    subprocess.check_call(
        ["git", "commit", "--allow-empty", "-m", "Initial commit"],
        stderr=DEVNULL,
        stdout=DEVNULL,
    )


def checkout_branch(target_branch: str, base_branch: str) -> None:
    """Checkout the target branch, creating it from base_branch if provided."""
    if not _is_in_git_repo():
        _init_repo()

    _check_empty_git_history()

    if (Path.cwd() / ".no-checkout").exists():
        fail(
            "This repository does not allow automatic branch checkouts. Please remove the .no-checkout file and try again."
        )

    if not branch_exists(base_branch):
        fail(f"Base branch '{base_branch}' does not exist.")

    if branch_exists(target_branch):
        # Just checkout the existing branch
        ret = subprocess.check_call(
            ["git", "checkout", target_branch], stderr=DEVNULL, stdout=DEVNULL
        )
    else:
        # Create new branch from base
        ret = subprocess.check_call(
            ["git", "checkout", "-b", target_branch, base_branch],
            stderr=DEVNULL,
            stdout=DEVNULL,
        )

    if ret != 0:
        fail(f"Failed to checkout branch '{target_branch}' from '{base_branch}'.")


def resolve_default_base_branch() -> str:
    """Return 'main' if it exists, otherwise 'master'."""
    if branch_exists("main"):
        return "main"
    if branch_exists("master"):
        return "master"
    fail("No base branch specified and neither 'main' nor 'master' branches exist.")
    return ""  # Unreachable
