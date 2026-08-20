"""The refiner: re-plans the unfinished half of an existing plan."""

from pathlib import Path
from typing import Any

from ralpher.agents.base import PlanningAgent
from ralpher.backend import Plan
from ralpher.models import Project, Task

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


class Refiner(PlanningAgent):
    """Rewrites an existing plan, leaving the already-completed tasks alone.

    Unlike the planner, this agent runs against a plan that may be half
    implemented, so it takes the completed tasks as input and is held to them:
    `validate` rejects any plan that dropped or edited one.
    """

    role = "refiner"
    template = "refine"

    def __init__(
        self,
        project: Project,
        *,
        input_path: Path,
        completed: list[Task],
    ) -> None:
        """`input_path` holds the refinement instructions; `completed` is frozen."""
        super().__init__(project)
        self.input_path = input_path
        self.completed = completed

    def variables(self) -> dict[str, Any]:
        return {
            "design_path": str(self.project.design_md),
            "tasks_path": str(self.project.tasks_toml),
            "input_path": str(self.input_path),
            "jj": self.project.jj,
            "completed_tasks": self.completed,
        }

    def validate(self, plan: Plan) -> str | None:
        return check_completed_tasks(self.completed, plan)
