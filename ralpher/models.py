import json
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel


class UserStory(BaseModel):
    id: str
    title: str
    description: str
    acceptance_criteria: list[str]
    priority: int
    passes: bool = False
    notes: str = ""


class PRD(BaseModel):
    project: str
    description: str
    user_stories: list[UserStory]

    @staticmethod
    def load(path: Path) -> "PRD":
        if not path.exists():
            raise FileNotFoundError(f"{path} not found.")
        return PRD.model_validate(json.loads(path.read_text()))

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.model_dump(), indent=2))

    def failed_stories(self) -> list[UserStory]:
        return [s for s in self.user_stories if not s.passes]


class Status(BaseModel):
    status: Literal["running", "idle", "error", "completed"]
    label: str
    active_user_story: str | None = None

    @property
    def icon(self) -> str:
        return {"running": "🟢", "idle": "🟡", "error": "❌", "completed": "✅"}[
            self.status
        ]

    @property
    def color(self) -> str:
        return {
            "running": "green",
            "idle": "yellow",
            "error": "red",
            "completed": "green",
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
