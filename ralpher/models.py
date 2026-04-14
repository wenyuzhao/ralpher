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

    @staticmethod
    def load(path: Path) -> "ProjectPlan":
        if not path.exists():
            raise FileNotFoundError(f"{path} not found.")
        return ProjectPlan.model_validate(json.loads(path.read_text()))

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.model_dump(), indent=2))

    def failed_tasks(self) -> list[Task]:
        return [t for t in self.tasks if not t.passes]


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
    def clear(task_dir: Path):
        questions_path = task_dir / "questions.json"
        if questions_path.exists():
            questions_path.unlink()

    @staticmethod
    def load(task_dir: Path) -> Optional["Questions"]:
        questions_path = task_dir / "questions.json"
        if not questions_path.exists():
            return None
        return Questions.model_validate(json.loads(questions_path.read_text()))


class RunInfo(BaseModel):
    id: str
    max_iterations: int
    model: Optional[str] = None
    current_iteration: int | None = None
    current_task_id: Optional[str] = None

    @property
    def branch(self) -> str:
        return f"ralph/{self.id[18:]}"

    @property
    def task_dir(self) -> Path:
        return Path.cwd() / ".ralpher" / "projects" / self.id

    @property
    def progress_file(self) -> Path:
        return self.task_dir / "progress.md"

    @property
    def plan_json_file(self) -> Path:
        return self.task_dir / "plan.json"

    @property
    def plan_doc_file(self) -> Path:
        return self.task_dir / "PLAN.md"

    @property
    def questions_file(self) -> Path:
        return self.task_dir / "questions.json"

    @property
    def current_task_file(self) -> Path:
        return self.task_dir / "current_task.json"

    def load_current_task(self) -> Task:
        return Task.model_validate(json.loads(self.current_task_file.read_text()))

    def save_current_task(self, task: Task) -> None:
        self.current_task_file.write_text(json.dumps(task.model_dump(), indent=2))

    def remove_current_task(self) -> None:
        if self.current_task_file.exists():
            self.current_task_file.unlink()

    def load_original_current_task(self) -> Task:
        assert self.current_task_id is not None
        plan = self.load_plan()
        for t in plan.tasks:
            if t.id == self.current_task_id:
                return t
        raise ValueError(f"Task with id {self.current_task_id} not found in plan.json")

    def load_plan(self) -> ProjectPlan:
        plan_path = self.task_dir / "plan.json"
        if not plan_path.exists():
            raise FileNotFoundError(f"plan.json not found in {self.task_dir}")
        return ProjectPlan.load(plan_path)
