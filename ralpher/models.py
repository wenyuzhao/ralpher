import json
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel


class Task(BaseModel):
    id: str
    title: str
    description: str
    acceptance_criteria: list[str]
    priority: int
    passes: bool = False
    notes: str = ""


class ProjectPlan(BaseModel):
    project: str
    description: str
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

    @staticmethod
    def clear(project_dir: Path):
        if project_dir.name == "questions.json":
            questions_path = project_dir
        else:
            questions_path = project_dir / "questions.json"
        if questions_path.exists():
            questions_path.unlink()

    @staticmethod
    def load(project_dir: Path) -> Optional["Questions"]:
        if project_dir.name == "questions.json":
            questions_path = project_dir
        else:
            questions_path = project_dir / "questions.json"
        if not questions_path.exists():
            return None
        return Questions.model_validate(json.loads(questions_path.read_text()))


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
    def branch(self) -> str:
        return f"ralph/{self.id[18:]}"

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
    def plan_json(self) -> Path:
        return self.project_dir / "plan.json"

    @property
    def questions_json(self) -> Path:
        return self.project_dir / "questions.json"

    @property
    def current_task_json(self) -> Path:
        return self.project_dir / "current_task.json"

    def load_plan(self) -> ProjectPlan | None:
        if not self.plan_json.exists():
            return None
        return ProjectPlan.model_validate(json.loads(self.plan_json.read_text()))

    def save_plan(self, plan: ProjectPlan) -> None:
        self.plan_json.write_text(plan.model_dump_json())

    def load_questions(self) -> Questions | None:
        if not self.questions_json.exists():
            return None
        return Questions.model_validate(json.loads(self.questions_json.read_text()))

    def load_current_task(self) -> Task | None:
        if not self.current_task_json.exists():
            return None
        return Task.model_validate(json.loads(self.current_task_json.read_text()))

    def save_current_task(self, task: Task) -> None:
        self.current_task_json.write_text(task.model_dump_json())

    def remove_current_task(self) -> None:
        if self.current_task_json.exists():
            self.current_task_json.unlink()
