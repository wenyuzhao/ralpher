import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, field_validator


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
# ``backend`` key in settings.json both flow through ``normalize_backend``.
_BACKEND_ALIASES: dict[str, BackendKind] = {
    "claude-code": "claude-code",
    "claude": "claude-code",
    "cc": "claude-code",
    "antigravity": "antigravity",
    "agy": "antigravity",
}

DEFAULT_BACKEND: BackendKind = "claude-code"


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
    # Per-kind model pins ("plan", "refine", "loop", "verify", "extract-tasks"),
    # overriding whichever backend is active and its `default_models`. A pin may
    # carry a ``:<level>`` reasoning-effort suffix; see `Backend.split_effort`.
    models: dict[str, str] = {}
    # Default coding-agent backend for this checkout. Overridden per run by the
    # ``--backend`` CLI flag. Accepts aliases (e.g. "cc", "agy") via the
    # validator below, which stores the canonical BackendKind.
    backend: BackendKind = DEFAULT_BACKEND
    # Run the agent's shell tool in an OS sandbox: for claude-code so the
    # read-only .ralpher deny rule is enforced against shell writes too, for
    # antigravity as `agy --sandbox`. Enabled by default; the loop's
    # --sandbox/--no-sandbox flag overrides this per run.
    sandbox: bool = True
    # This checkout is managed with Jujutsu: the agent is told to drive `jj`
    # rather than `git`. Overridden per run by the --jj/--no-jj flag.
    jj: bool = False

    @field_validator("backend", mode="before")
    @classmethod
    def _normalize_backend(cls, value: object) -> object:
        if isinstance(value, str):
            return normalize_backend(value)
        return value

    @classmethod
    def load(cls) -> Settings:
        path = ralpher_root() / "settings.json"
        if not path.exists():
            return cls()
        return cls.model_validate(json.loads(path.read_text()))


def resolve_backend(cli_backend: str | None) -> BackendKind:
    """Resolve the backend for a run: the ``--backend`` flag wins, else settings.json.

    Mirrors how ``--sandbox`` falls back to ``Settings.sandbox``.
    """
    if cli_backend is not None:
        return normalize_backend(cli_backend)
    return Settings.load().backend


def resolve_jj(cli_jj: bool | None) -> bool:
    """Resolve the VCS for a run: the ``--jj/--no-jj`` flag wins, else settings.json.

    Mirrors how ``--sandbox`` falls back to ``Settings.sandbox``.
    """
    if cli_jj is not None:
        return cli_jj
    return Settings.load().jj


class Task(BaseModel):
    id: str
    title: str
    description: str
    acceptance_criteria: list[str]
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
    label: str
    description: str


class Question(BaseModel):
    header: str
    question: str
    options: list[QuestionOption]


class Questions(BaseModel):
    questions: list[Question]


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
    backend: BackendKind = DEFAULT_BACKEND
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
    def config_json(self) -> Path:
        return self.project_dir / "config.json"

    def load_config(self) -> ProjectConfig | None:
        if not self.config_json.exists():
            return None
        return ProjectConfig.model_validate(json.loads(self.config_json.read_text()))

    def save_config(self, config: ProjectConfig) -> None:
        self.config_json.write_text(config.model_dump_json(indent=2))

    @property
    def prompt_md(self) -> Path:
        return self.project_dir / "PROMPT.md"

    @property
    def plan_md(self) -> Path:
        return self.project_dir / "PLAN.md"

    @property
    def progress_md(self) -> Path:
        return self.project_dir / "progress.md"

    @property
    def tasks_json(self) -> Path:
        return self.project_dir / "tasks.json"

    @property
    def questions_json(self) -> Path:
        return self.project_dir / "questions.json"

    @property
    def current_task_json(self) -> Path:
        return self.project_dir / "current_task.json"

    def load_tasks(self) -> Tasks | None:
        if not self.tasks_json.exists():
            return None
        return Tasks.model_validate(json.loads(self.tasks_json.read_text()))

    def save_tasks(self, tasks: Tasks) -> None:
        self.tasks_json.write_text(tasks.model_dump_json(indent=2))

    def load_questions(self) -> Questions | None:
        if not self.questions_json.exists():
            return None
        return Questions.model_validate(json.loads(self.questions_json.read_text()))

    def save_current_task(self, task: Task) -> None:
        self.current_task_json.write_text(
            task.model_dump_json(indent=2, exclude={"passes"})
        )

    def remove_current_task(self) -> None:
        if self.current_task_json.exists():
            self.current_task_json.unlink()
