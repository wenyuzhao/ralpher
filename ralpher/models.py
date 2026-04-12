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
