import json
from pathlib import Path
from typing import Literal

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
    branch_name: str
    description: str
    user_stories: list[UserStory]

    @staticmethod
    def load(path: Path) -> "PRD":
        if not path.exists():
            raise FileNotFoundError(f"{path} not found.")
        return PRD.model_validate(json.loads(path.read_text()))

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
