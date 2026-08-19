import json
import shutil
import tomllib
from pathlib import Path
from typing import Literal

import tomli_w
from pydantic import BaseModel, Field, field_validator


def ralpher_root() -> Path:
    """Root directory holding all ralpher state, relative to the current cwd.

    Single source of truth for the location: both the project file layout
    (via ``Project.ralpher_dir``) and the read-only deny rules applied to the
    coding-agent subprocess derive from this, so they cannot drift apart.
    """
    return Path.cwd() / ".ralpher"


# Which coding-agent backend drives a run. ``claude-code`` shells out to the
# ``claude`` CLI; ``antigravity`` shells out to Google's ``agy`` CLI (Gemini)
# instead. Both are driven through the same ``run_agent`` /
# ``run_agent_plan_mode`` dispatcher, which selects on the resolved backend
# (see ``ralpher.backend``).
BackendKind = Literal["claude-code", "antigravity"]

# CLI / settings aliases accepted for each backend. ``--backend`` and the
# ``backend`` key in settings.toml both flow through ``normalize_backend``.
_BACKEND_ALIASES: dict[str, BackendKind] = {
    "claude-code": "claude-code",
    "claude": "claude-code",
    "cc": "claude-code",
    "antigravity": "antigravity",
    "agy": "antigravity",
}

# Order in which backends are auto-detected when neither --backend nor the
# settings.toml `backend` key says otherwise: the first one whose CLI is on
# PATH wins, and the first entry is also the fallback when none is installed
# (so the resulting `check_prerequisites` error names the preferred CLI).
_BACKEND_PREFERENCE: tuple[BackendKind, ...] = ("claude-code", "antigravity")


def detect_default_backend() -> BackendKind:
    """The default backend for this machine: the first installed CLI, in preference order.

    Looks each backend's executable up on PATH (``claude``, then ``agy``) via the
    backend registry, so the executable name stays owned by the backend class.
    Falls back to the first preference when neither CLI is installed.
    """
    # Imported lazily: ralpher.backend imports this module.
    from ralpher.backend import BACKENDS

    for kind in _BACKEND_PREFERENCE:
        if shutil.which(BACKENDS[kind].executable):
            return kind
    return _BACKEND_PREFERENCE[0]


def normalize_backend(value: str) -> BackendKind:
    """Resolve a user-supplied backend name/alias to its canonical ``BackendKind``.

    Raises ``ValueError`` (surfaced by pydantic when validating settings, and
    caught by the CLI for ``--backend``) on an unknown value.
    """
    key = value.strip().lower()
    if key not in _BACKEND_ALIASES:
        valid = ", ".join(sorted(set(_BACKEND_ALIASES)))
        raise ValueError(f"Unknown backend '{value}'. Valid values: {valid}.")
    return _BACKEND_ALIASES[key]


class Settings(BaseModel):
    # Per-kind model pins ("plan", "refine", "loop", "verify") or a single
    # string applied to all kinds, overriding whichever backend is
    # active and its `default_models`. A pin may carry a ``:<level>``
    # reasoning-effort suffix; see `Backend.split_effort`.
    models: dict[str, str] | str = {}
    # Default coding-agent backend for this checkout. Unset, it is detected from
    # which CLI is installed (see `detect_default_backend`). Overridden per run
    # by the ``--backend`` CLI flag. Accepts aliases (e.g. "cc", "agy") via the
    # validator below, which stores the canonical BackendKind.
    backend: BackendKind = Field(default_factory=detect_default_backend)
    # Run the agent's shell tool in an OS sandbox: for claude-code so the
    # read-only .ralpher deny rule is enforced against shell writes too, for
    # antigravity as `agy --sandbox`. Enabled by default; the loop's
    # --sandbox/--no-sandbox flag overrides this per run.
    sandbox: bool = True
    # This checkout is managed with Jujutsu: the agent is told to drive `jj`
    # rather than `git`. Overridden per run by the --jj/--no-jj flag.
    jj: bool = False
    # Extra CLI args appended verbatim to every backend invocation (e.g.
    # ["--add-dir", "/extra/path"]). No CLI flag overrides this; it is
    # settings.toml-only. Applied by each backend's `build_command` via
    # `Backend._extra_args`.
    extra_args: list[str] = []

    def get_model(self, kind: str) -> str | None:
        if isinstance(self.models, str):
            return self.models
        return self.models.get(kind)

    @field_validator("backend", mode="before")
    @classmethod
    def _normalize_backend(cls, value: object) -> object:
        if isinstance(value, str):
            return normalize_backend(value)
        return value

    @classmethod
    def load(cls) -> Settings:
        path = ralpher_root() / "settings.toml"
        if not path.exists():
            return cls()
        with path.open("rb") as f:
            return cls.model_validate(tomllib.load(f))


def resolve_backend(cli_backend: str | None) -> BackendKind:
    """Resolve the backend for a run: the ``--backend`` flag wins, else settings.toml.

    Mirrors how ``--sandbox`` falls back to ``Settings.sandbox``.
    """
    if cli_backend is not None:
        return normalize_backend(cli_backend)
    return Settings.load().backend


def resolve_jj(cli_jj: bool | None) -> bool:
    """Resolve the VCS for a run: the ``--jj/--no-jj`` flag wins, else settings.toml.

    Mirrors how ``--sandbox`` falls back to ``Settings.sandbox``.
    """
    if cli_jj is not None:
        return cli_jj
    return Settings.load().jj


class PlannedTask(BaseModel):
    """One unit of work as the planning agent hands it over.

    Carries no run state: whether a task has passed is ralpher's bookkeeping,
    not something the planner gets to assert. Keeping it off this model also
    keeps `passes` out of the JSON schema the planning agent is given.
    """

    id: str = Field(
        description="Unique identifier, numbered sequentially in list order with no gaps: the first task is T-001, the second T-002, the third T-003, and so on. Always three digits; at most 999 tasks."
    )
    title: str = Field(description="Short descriptive name for the task.")
    description: str = Field(
        description="Clear, concise explanation of what needs to be done and why."
    )
    acceptance_criteria: list[str] = Field(
        description=(
            "Specific, verifiable conditions that must all hold for the task to "
            "be considered complete."
        )
    )


class Task(PlannedTask):
    passes: bool = False


class Tasks(BaseModel):
    tasks: list[Task]

    def failed_tasks(self) -> list[Task]:
        return [t for t in self.tasks if not t.passes]

    def get_task_by_id(self, task_id: str) -> Task | None:
        for t in self.tasks:
            if t.id == task_id:
                return t
        return None

    def to_markdown(self) -> str:
        """Render the task list as human-readable markdown.

        A derived view of `tasks.toml`, rewritten from scratch on every save —
        nothing ever reads it back, so it carries no state the TOML doesn't.
        """
        done = sum(1 for t in self.tasks if t.passes)
        lines = ["# Tasks", "", f"{done} of {len(self.tasks)} complete.", ""]
        for t in self.tasks:
            lines.append(f"- [{'x' if t.passes else ' '}] **{t.id}** — {t.title}")
        for t in self.tasks:
            lines += [
                "",
                f"## {t.id} — {t.title}",
                "",
                f"**Status:** {'✅ passed' if t.passes else '⬜ pending'}",
                "",
                t.description,
                "",
                "**Acceptance criteria:**",
                "",
            ]
            lines += [f"- {c}" for c in t.acceptance_criteria]
        return "\n".join(lines) + "\n"


class Status(BaseModel):
    status: Literal["running", "idle", "error", "completed", "starting"]
    label: str
    active_task: str | None = None

    @property
    def icon(self) -> str:
        return {
            "running": "🟢",
            "idle": "🟡",
            "error": "❌",
            "completed": "✅",
            "starting": "🟡",
        }[self.status]

    @property
    def color(self) -> str:
        return {
            "running": "green",
            "idle": "yellow",
            "error": "red",
            "completed": "green",
            "starting": "yellow",
        }[self.status]


class QuestionOption(BaseModel):
    label: str = Field(description="A short label for the option.")
    description: str = Field(
        description="A detailed description of the option to help the user choose."
    )


class Question(BaseModel):
    header: str = Field(
        description="A short header in 1-2 words describing the question."
    )
    question: str = Field(
        description="The question to ask the user. Must be a multiple-choice single-answer question."
    )
    options: list[QuestionOption] = Field(description="A list of 2-6 concrete options.")


class Questions(BaseModel):
    questions: list[Question] = Field(
        description="A list of clarification questions to ask the user."
    )


class ProjectConfig(BaseModel):
    base_branch: str
    target_branch: str


class Project(BaseModel):
    id: str
    max_iterations: int | None = None
    current_iteration: int | None = None
    current_task_id: str | None = None
    # Coding-agent backend for this run. Resolved once by each command (CLI
    # --backend flag, else Settings.backend) and read by run_agent /
    # run_agent_plan_mode to dispatch to the right SDK.
    backend: BackendKind = Field(default_factory=detect_default_backend)
    # Whether the agent subprocess runs with OS-level shell sandboxing for this
    # run. Resolved once by the loop command (CLI flag, else Settings.sandbox)
    # and read by the backend when building its argv.
    sandbox: bool = False
    # Whether the agent is told to use Jujutsu (`jj`) instead of `git` for this
    # run. Resolved once by each command (CLI --jj/--no-jj flag, else
    # Settings.jj) and rendered into the prompts as the `jj` template variable.
    # Ralpher's own branch bookkeeping stays on git either way, which is why a
    # jj run must be colocated (see `check_jj_prerequisites`).
    jj: bool = False

    @property
    def ralpher_dir(self) -> Path:
        return ralpher_root()

    @property
    def project_dir(self) -> Path:
        return self.ralpher_dir / "projects" / self.id

    @property
    def config_toml(self) -> Path:
        return self.project_dir / "config.toml"

    def load_config(self) -> ProjectConfig | None:
        if not self.config_toml.exists():
            return None
        with self.config_toml.open("rb") as f:
            return ProjectConfig.model_validate(tomllib.load(f))

    def save_config(self, config: ProjectConfig) -> None:
        self.config_toml.write_text(tomli_w.dumps(config.model_dump(exclude_none=True)))

    @property
    def prompt_md(self) -> Path:
        return self.project_dir / "prompt.md"

    @property
    def design_md(self) -> Path:
        return self.project_dir / "design.md"

    @property
    def progress_md(self) -> Path:
        return self.project_dir / "progress.md"

    @property
    def tasks_toml(self) -> Path:
        return self.project_dir / "tasks.toml"

    @property
    def tasks_md(self) -> Path:
        return self.project_dir / "tasks.md"

    @property
    def questions_json(self) -> Path:
        return self.project_dir / "questions.json"

    @property
    def current_task_toml(self) -> Path:
        return self.project_dir / "current_task.toml"

    def load_tasks(self) -> Tasks | None:
        if not self.tasks_toml.exists():
            return None
        with self.tasks_toml.open("rb") as f:
            return Tasks.model_validate(tomllib.load(f))

    def save_tasks(self, tasks: Tasks) -> None:
        self.tasks_toml.write_text(tomli_w.dumps(tasks.model_dump()))
        # tasks.md is a read-only mirror for humans; every writer goes through
        # here, so the two files can never drift.
        self.tasks_md.write_text(tasks.to_markdown())

    def save_planned_tasks(self, planned: list[PlannedTask]) -> None:
        """Persist a task list straight from the planning agent.

        `plan` writes tasks.toml for the first time, but `refine` rewrites it —
        possibly partway through a run — so a task that already passed and kept
        its id stays passed instead of being implemented all over again.
        """
        existing = self.load_tasks()
        already_passed = (
            {t.id for t in existing.tasks if t.passes} if existing else set()
        )
        self.save_tasks(
            Tasks(
                tasks=[
                    Task(**t.model_dump(), passes=t.id in already_passed)
                    for t in planned
                ]
            )
        )

    def load_questions(self) -> Questions | None:
        if not self.questions_json.exists():
            return None
        return Questions.model_validate(json.loads(self.questions_json.read_text()))

    def save_current_task(self, task: Task) -> None:
        self.current_task_toml.write_text(
            tomli_w.dumps(task.model_dump(exclude={"passes"}))
        )

    def remove_current_task(self) -> None:
        if self.current_task_toml.exists():
            self.current_task_toml.unlink()
