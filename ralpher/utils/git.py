import shutil
import subprocess
from pathlib import Path
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


def _ensure_repo() -> None:
    """Ensure we're in a git repo with history and checkout is allowed."""
    if not _is_in_git_repo():
        _init_repo()

    _check_empty_git_history()


def checkout_existing_branch(branch: str) -> None:
    """Checkout an existing branch."""
    if not branch_exists(branch):
        fail(f"Branch '{branch}' does not exist.")

    ret = subprocess.check_call(
        ["git", "checkout", branch], stderr=DEVNULL, stdout=DEVNULL
    )
    if ret != 0:
        fail(f"Failed to checkout branch '{branch}'.")


def checkout_branch(target_branch: str, base_branch: str) -> None:
    """Checkout the target branch, creating it from base_branch if provided."""
    _ensure_repo()

    if not branch_exists(base_branch):
        fail(f"Base branch '{base_branch}' does not exist.")

    if branch_exists(target_branch):
        # Just checkout the existing branch
        ret = subprocess.check_call(
            ["git", "checkout", target_branch], stderr=DEVNULL, stdout=DEVNULL
        )
    else:
        if (Path.cwd() / ".no-branch").exists():
            fail(
                "This repository does not allow automatic branch creation. Please remove the .no-branch file and try again."
            )
        # Create new branch from base
        ret = subprocess.check_call(
            ["git", "checkout", "-b", target_branch, base_branch],
            stderr=DEVNULL,
            stdout=DEVNULL,
        )

    if ret != 0:
        fail(f"Failed to checkout branch '{target_branch}' from '{base_branch}'.")


def jj_root() -> str | None:
    """Return the root of the jj workspace containing CWD, or None if there is none."""
    try:
        return subprocess.check_output(["jj", "root"], stderr=DEVNULL).decode().strip()
    except subprocess.CalledProcessError, OSError:
        return None


def check_jj_prerequisites() -> None:
    """Exit with an error unless `--jj` can actually work in this checkout.

    Only the *agent* is switched to `jj`; ralpher keeps doing its own branch
    bookkeeping with `git` (see `checkout_branch`). So the workspace has to be
    colocated — in a jj-only repo there is no `.git` at the root and
    `_ensure_repo` would happily `git init` a second, empty repository inside
    it.
    """
    if not shutil.which("jj"):
        fail(
            "'jj' CLI not found on PATH. Install Jujutsu (https://jj-vcs.github.io/jj/), "
            "or drop --jj to let the agent use git."
        )

    root = jj_root()
    if root is None:
        fail("--jj was given but the current directory is not inside a jj repository.")

    if not (Path(root) / ".git").exists():
        fail(
            f"The jj repository at '{root}' is not colocated with git, and ralpher "
            "manages its own branches with git. Re-create it with "
            "[i]jj git init --colocate[/], or drop --jj."
        )


def resolve_default_base_branch() -> str:
    """Return 'main' if it exists, otherwise 'master'."""
    if branch_exists("main"):
        return "main"
    if branch_exists("master"):
        return "master"
    fail("No base branch specified and neither 'main' nor 'master' branches exist.")
    return ""  # Unreachable
