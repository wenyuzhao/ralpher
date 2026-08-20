"""The verifier: an independent second opinion on the worker's task."""

from typing import Any

from pydantic import BaseModel, Field

from ralpher.agents.base import OutputAgent


class Result(BaseModel):
    task_passed: bool = Field(
        description="Whether the task is fully implemented and passes all checks."
    )
    notes: str | None = Field(
        default=None,
        description=(
            "When task_passed is false, a markdown-formatted note describing "
            "what is still incomplete, which acceptance criteria are unmet, "
            "which checks failed and their error messages, and any hints for "
            "the next attempt. Null or empty when task_passed is true."
        ),
    )


class Verifier(OutputAgent[Result]):
    """Decides whether the current task actually passes.

    Runs in a fresh session with none of the worker's context, so it cannot
    rubber-stamp its own work. It inspects the repo and the committed history
    rather than taking the worker's report on trust.
    """

    role = "verifier"
    template = "verify"
    output = Result

    def variables(self) -> dict[str, Any]:
        return {
            "current_task_path": str(self.project.current_task_toml),
            "design_path": str(self.project.design_md),
            "tasks_path": str(self.project.tasks_toml),
            "jj": self.project.jj,
        }
