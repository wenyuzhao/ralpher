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
    status: Literal["running", "idle", "error", "completed", "starting"]
    label: str
    active_user_story: str | None = None

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
    current_user_story_id: Optional[str] = None

    @property
    def branch(self) -> str:
        return f"ralph/{self.id[18:]}"

    @property
    def task_dir(self) -> Path:
        return Path.cwd() / ".ralpher" / "tasks" / self.id

    @property
    def progress_file(self) -> Path:
        return self.task_dir / "progress.md"

    @property
    def prd_json_file(self) -> Path:
        return self.task_dir / "prd.json"

    @property
    def prd_doc_file(self) -> Path:
        return self.task_dir / "PRD.md"

    @property
    def questions_file(self) -> Path:
        return self.task_dir / "questions.json"

    @property
    def current_user_story_file(self) -> Path:
        return self.task_dir / "current_user_story.json"

    def load_current_user_story(self) -> UserStory:
        return UserStory.model_validate(
            json.loads(self.current_user_story_file.read_text())
        )

    def save_current_user_story(self, story: UserStory) -> None:
        self.current_user_story_file.write_text(
            json.dumps(story.model_dump(), indent=2)
        )

    def remove_current_user_story(self) -> None:
        if self.current_user_story_file.exists():
            self.current_user_story_file.unlink()

    def load_original_current_user_story(self) -> UserStory:
        assert self.current_user_story_id is not None
        prd = self.load_prd()
        for s in prd.user_stories:
            if s.id == self.current_user_story_id:
                return s
        raise ValueError(
            f"User story with id {self.current_user_story_id} not found in prd.json"
        )

    def load_prd(self) -> PRD:
        prd_path = self.task_dir / "prd.json"
        if not prd_path.exists():
            raise FileNotFoundError(f"prd.json not found in {self.task_dir}")
        return PRD.load(prd_path)
