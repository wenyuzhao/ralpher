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


def create_branch(branch: str, start_point: str) -> None:
    """Create a new branch at start_point without switching to it."""
    _check_empty_git_history()

    subprocess.check_call(
        ["git", "branch", branch, start_point], stderr=DEVNULL, stdout=DEVNULL
    )


def checkout_branch(target_branch: str, base_branch: str) -> None:
    """Checkout the target branch, creating it from base_branch if provided."""
    _check_empty_git_history()

    # Create new branch from base
    subprocess.check_call(
        ["git", "checkout", "-b", target_branch, base_branch],
        stderr=DEVNULL,
        stdout=DEVNULL,
    )


def resolve_default_base_branch() -> str:
    """Return 'main' if it exists, otherwise 'master'."""
    if branch_exists("main"):
        return "main"
    if branch_exists("master"):
        return "master"
    fail("No base branch specified and neither 'main' nor 'master' branches exist.")
    return ""  # Unreachable
