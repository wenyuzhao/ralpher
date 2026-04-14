import subprocess

from ralpher.utils.error import fail


def get_current_branch() -> str | None:
    """Return the current branch name, or None if HEAD doesn't exist."""
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
    except subprocess.CalledProcessError:
        return None


def branch_exists(branch: str) -> bool:
    """Check whether a local branch exists."""
    result = (
        subprocess.check_output(
            ["git", "branch", "--list", branch], stderr=subprocess.DEVNULL
        )
        .decode()
        .strip()
    )
    return bool(result)


def checkout_branch(target_branch: str, base_branch: str) -> None:
    """Checkout the target branch, creating it from base_branch if provided.

    If no git history exists (no HEAD), creates 'main' with an empty commit first.
    """
    current = get_current_branch()

    if current is None:
        # No commits yet — create main first
        subprocess.check_call(["git", "checkout", "-b", "main"])
        subprocess.check_call(
            ["git", "commit", "--allow-empty", "-m", "Initial commit"]
        )
        if base_branch is None:
            base_branch = "main"

    # Create new branch from base
    subprocess.check_call(
        ["git", "checkout", "-b", target_branch, base_branch],
        stderr=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
    )


def resolve_default_base_branch() -> str:
    """Return 'main' if it exists, otherwise 'master'."""
    if branch_exists("main"):
        return "main"
    if branch_exists("master"):
        return "master"
    fail("No base branch specified and neither 'main' nor 'master' branches exist.")
    return ""  # Unreachable
