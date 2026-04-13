from pathlib import Path
import json
import datetime

from ...models import PRD, Status


class Hooks:
    def __init__(self):
        self.task_id: str
        self.task_dir: Path
        self.max_iterations: int
        self.start_time: datetime.datetime
        self.total_iterations = 0
        self.status: Status = Status(status="idle", label="Idle")

    async def init(self, task_dir: Path, max_iterations: int):
        self.task_id = task_dir.name
        self.task_dir = task_dir
        self.max_iterations = max_iterations
        self.start_time = datetime.datetime.now()

    async def update(self): ...

    def load_prd(self) -> PRD | None:
        prd_file = self.task_dir / "prd.json"
        if not prd_file.exists():
            return None
        return PRD.model_validate(json.loads(prd_file.read_text()))

    async def on_cancel(self, message: str | None = None):
        label = f"Canceled: {message}" if message else "Canceled"
        self.status = Status(status="idle", label=label)
        await self.update()

    async def on_error(self, message: str):
        self.status = Status(status="error", label=message)
        await self.update()

    async def on_extract_start(self):
        self.status = Status(status="running", label="Extracting PRD")
        await self.update()

    async def on_extract_end(self):
        self.status = Status(status="running", label="Extracted PRD")
        await self.update()

    async def on_loop_start(self):
        self.status = Status(status="running", label="Loop Started")
        await self.update()

    async def on_iteration_start(self, index: int, us: str):
        prd = self.load_prd()
        assert prd is not None
        user_story = next((s for s in prd.user_stories if s.id == us), None)
        label = f"Iteration {index} / {self.max_iterations}"
        if user_story:
            label += f": *{user_story.id}* - {user_story.title}"
        self.status = Status(status="running", label=label)
        await self.update()

    async def on_iteration_end(self, index: int, us: str):
        prd = self.load_prd()
        assert prd is not None
        user_story = next((s for s in prd.user_stories if s.id == us), None)
        label = f"Iteration {index} / {self.max_iterations}"
        if user_story:
            result = "PASSED" if user_story.passes else "FAILED"
            label += f": *{user_story.id}* - {user_story.title} ({result})"
        self.status = Status(status="running", label=label)
        await self.update()

    async def on_loop_end(self, iterations: int, completed: bool):
        self.total_iterations = iterations
        if completed:
            if iterations == 0:
                label = f"Project Completed"
            else:
                label = f"Project Completed in {iterations} iterations"
            status = "completed"
        else:
            label = f"Loop finished in {iterations} iterations (*INCOMPLETE*)"
            status = "idle"
        self.status = Status(status=status, label=label)
        await self.update()


class HooksManager:
    def __init__(self, hooks: list["Hooks"] | None = None):
        if hooks is None:
            from .notion import NotionHooks

            hooks = [NotionHooks()]
        self.hooks = hooks

    async def init(self, task_dir: Path, max_iterations: int):
        for h in self.hooks:
            await h.init(task_dir, max_iterations)

    async def on_cancel(self, message: str | None = None):
        for h in self.hooks:
            await h.on_cancel(message)

    async def on_error(self, message: str):
        for h in self.hooks:
            await h.on_error(message)

    async def on_extract_start(self):
        for h in self.hooks:
            await h.on_extract_start()

    async def on_extract_end(self):
        for h in self.hooks:
            await h.on_extract_end()

    async def on_loop_start(self):
        for h in self.hooks:
            await h.on_loop_start()

    async def on_iteration_start(self, index: int, us: str):
        for h in self.hooks:
            await h.on_iteration_start(index, us)

    async def on_iteration_end(self, index: int, us: str):
        for h in self.hooks:
            await h.on_iteration_end(index, us)

    async def on_loop_end(self, iterations: int, completed: bool):
        for h in self.hooks:
            await h.on_loop_end(iterations, completed)
