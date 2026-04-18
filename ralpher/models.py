import json
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel


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

    def get_task_by_id(self, task_id: str) -> Optional[Task]:
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
    model: Optional[str] = None
    max_iterations: int | None = None
    current_iteration: int | None = None
    current_task_id: Optional[str] = None

    @property
    def project_dir(self) -> Path:
        return Path.cwd() / ".ralpher" / "projects" / self.id

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
        self.current_task_json.write_text(task.model_dump_json(indent=2, exclude={"passes"}))

    def remove_current_task(self) -> None:
        if self.current_task_json.exists():
            self.current_task_json.unlink()
