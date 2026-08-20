"""The worker: implements one task per loop iteration."""

from typing import Any

from pydantic import BaseModel, Field

from ralpher.agents.base import OutputAgent
from ralpher.backend import context_file


class ProgressReport(BaseModel):
    """What the implementation session reports back about its iteration.

    The agent never writes the progress log itself — `.ralpher` is read-only to
    it — so it returns the entry it wants recorded and ralpher appends it.
    """

    notes: str = Field(
        description=(
            "Markdown body of this iteration's progress log entry: what was "
            "implemented, which files changed, which quality checks were run "
            "and their outcome (with the exact error output of any that still "
            "fail), and learnings for future iterations. Do not include a "
            "date/task heading or a trailing '---' separator — those are added "
            "for you."
        )
    )


class Worker(OutputAgent[ProgressReport]):
    """Implements the current task and reports what it did.

    The only agent that writes to the repo, so it is the only one that commits.
    """

    role = "worker"
    template = "iterate"
    output = ProgressReport

    def variables(self) -> dict[str, Any]:
        return {
            "current_task_path": str(self.project.current_task_toml),
            "design_path": str(self.project.design_md),
            "tasks_path": str(self.project.tasks_toml),
            "progress_path": str(self.project.progress_md),
            "jj": self.project.jj,
            # The context file the *running* CLI reads, so the worker updates
            # the one its own backend will pick up on the next iteration.
            "context_file": context_file(self.project.backend),
        }
