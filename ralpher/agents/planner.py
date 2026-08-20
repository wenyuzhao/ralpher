"""The planner: turns a user prompt into design.md + tasks.toml."""

from typing import Any

from ralpher.agents.base import PlanningAgent


class Planner(PlanningAgent):
    """Generates a project's plan from scratch.

    Reads only the user's prompt file and the codebase; both halves of the plan
    come back as structured output, so nothing here re-parses prose into tasks.
    """

    role = "planner"
    template = "plan"

    def variables(self) -> dict[str, Any]:
        return {
            "prompt_path": str(self.project.prompt_md),
            "jj": self.project.jj,
        }
