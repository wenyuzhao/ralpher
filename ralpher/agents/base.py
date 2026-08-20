"""The `Agent` abstraction: one job ralpher hands to a coding agent.

A backend (`ralpher.backend`) is *which CLI* runs; an agent is *what it is
asked to do*. Ralpher has four — planner, refiner, worker, verifier — and each
one is a fixed bundle of decisions that used to be spelled out again at every
call site:

- which prompt template to render, and with which variables,
- which pydantic schema the answer must validate against,
- whether the turn may write to the repo, and with which tools,
- which settings key configures it, and which log file it writes.

A subclass declares those; the call site becomes ``await Worker(project).run()``.

Two shapes of agent sit under `Agent`, because the backend offers two ways to
run a turn:

- `OutputAgent` — one turn, structured output, returns the validated model.
  The worker and the verifier.
- `PlanningAgent` — the plan-mode Q&A loop, which returns nothing and instead
  writes design.md and tasks.toml. The planner and the refiner.

Every knob a subclass declares can be overridden per role from an
``[agents.<role>]`` table in settings.toml (`AgentSettings`); the resolution
lives here, in one place, rather than in each subclass.
"""

import abc
from typing import Any, ClassVar

from pydantic import BaseModel

from ralpher.backend import Plan, run_agent, run_agent_plan_mode
from ralpher.models import AgentRole, AgentSettings, Project, Settings
from ralpher.prompts import render_prompt


class Agent(abc.ABC):
    """One job a coding agent is asked to do, bound to the `Project` it runs for."""

    #: Canonical role name. Selects this class in the `AGENTS` registry, keys
    #: this role's `[agents.<role>]` settings table and the backend's
    #: `default_models`, and names the run's log file.
    role: ClassVar[AgentRole]
    #: Prompt template in `ralpher.prompts` this agent renders, without the
    #: `.md` extension.
    template: ClassVar[str]
    #: Whether this role's turn is denied every write by default. Overridden per
    #: role by `AgentSettings.readonly`.
    readonly: ClassVar[bool] = False
    #: Tool allowlist for this role, for backends that take one. `None` leaves
    #: the backend's own choice (which, for a read-only claude turn, is
    #: `READONLY_TOOLS`). Overridden per role by `AgentSettings.tools`.
    tools: ClassVar[list[str] | None] = None

    def __init__(self, project: Project) -> None:
        self.project = project
        self.config: AgentSettings = Settings.load().for_agent(self.role)

    # --- subclass hooks --------------------------------------------------- #

    @abc.abstractmethod
    def variables(self) -> dict[str, Any]:
        """Template variables for this agent's prompt.

        Every variable the template references must appear here: the prompt
        environment uses `StrictUndefined`, so a missing one raises at render
        time rather than reaching the agent as an empty string.
        """

    # --- resolved configuration -------------------------------------------- #

    def prompt(self) -> str:
        """The rendered initial prompt for this agent's turn."""
        return render_prompt(self.template, **self.variables())

    @property
    def resolved_readonly(self) -> bool:
        return self.readonly if self.config.readonly is None else self.config.readonly

    @property
    def resolved_tools(self) -> list[str] | None:
        return self.tools if self.config.tools is None else self.config.tools

    @property
    def extra_args(self) -> list[str]:
        """This role's extra CLI args; the global ones are added by the backend."""
        return self.config.extra_args


class OutputAgent[T: BaseModel](Agent):
    """An agent that runs one turn and returns structured output.

    The turn is one-shot: there is no conversation to continue, so whatever the
    agent has to say has to come back on `output`. `.ralpher` is read-only to
    the agent, which is why the worker reports its progress entry rather than
    writing the log itself.
    """

    #: Schema the answer must validate against. Shipped to the CLI as a JSON
    #: schema, so its field descriptions are part of the prompt in practice.
    output: type[T]

    async def run(self) -> T:
        return await run_agent(
            role=self.role,
            prompt=self.prompt(),
            project=self.project,
            schema=self.output,
            model=self.config.model,
            readonly=self.resolved_readonly,
            tools=self.resolved_tools,
            extra_args=self.extra_args,
        )


class PlanningAgent(Agent):
    """An agent that produces a plan, through the backend's Q&A loop.

    Returns nothing: a plan's two halves are written straight to design.md and
    tasks.toml by the driver, which also re-prompts the agent when a returned
    plan fails a check. `validate` is this role's own check on top of the
    task-id invariant every plan must satisfy.
    """

    # Planning never writes to the repo — it reads the codebase and answers with
    # a plan — and the correction loop depends on that staying true.
    readonly = True

    def validate(self, plan: Plan) -> str | None:
        """Message rejecting `plan`, fed back as the next turn's prompt, or None."""
        return None

    async def run(self) -> None:
        await run_agent_plan_mode(
            role=self.role,
            prompt=self.prompt(),
            project=self.project,
            validate=self.validate,
            model=self.config.model,
            readonly=self.resolved_readonly,
            tools=self.resolved_tools,
            extra_args=self.extra_args,
            max_corrections=self.config.max_corrections,
        )
