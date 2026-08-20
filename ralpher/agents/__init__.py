"""The four agents ralpher runs, and the registry that names them.

An agent is *what a coding agent is asked to do*; a backend
(:mod:`ralpher.backend`) is *which CLI does it*. The two compose: every agent
here runs on whichever backend the project selected.

- ``planner`` → :class:`Planner` — prompt in, design.md + tasks.toml out
- ``refiner`` → :class:`Refiner` — the same, re-planning only the unfinished work
- ``worker`` → :class:`Worker` — implements one task, reports what it did
- ``verifier`` → :class:`Verifier` — independently decides whether it passed

Each is a subclass of :class:`ralpher.agents.base.Agent`, which owns everything
they have in common: rendering the prompt, resolving the per-role settings, and
handing the turn to the backend. Callers construct one and await ``run()``.
"""

from ralpher.models import AgentRole

from .base import Agent, OutputAgent, PlanningAgent
from .planner import Planner
from .refiner import Refiner, check_completed_tasks
from .verifier import Result, Verifier
from .worker import ProgressReport, Worker

__all__ = [
    "AGENTS",
    "Agent",
    "OutputAgent",
    "Planner",
    "PlanningAgent",
    "ProgressReport",
    "Refiner",
    "Result",
    "Verifier",
    "Worker",
    "check_completed_tasks",
]

AGENTS: dict[AgentRole, type[Agent]] = {
    "planner": Planner,
    "refiner": Refiner,
    "worker": Worker,
    "verifier": Verifier,
}
