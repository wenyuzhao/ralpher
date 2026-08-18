import datetime

import rich

from ...models import Project, Status, Tasks


class Hooks:
    name: str = "base"

    def __init__(self):
        self.project: Project
        self.start_time: datetime.datetime
        self.total_iterations = 0
        self.status: Status = Status(status="idle", label="Idle")

    def report_status(self):
        pass

    async def init(self, project: Project):
        self.project = project
        self.start_time = datetime.datetime.now().astimezone()
        self.status: Status = Status(status="starting", label="Starting")
        await self.update()

    async def update(self): ...

    def load_tasks(self) -> Tasks | None:
        return self.project.load_tasks()

    async def on_cancel(self, message: str | None = None):
        label = f"Canceled: {message}" if message else "Canceled"
        self.status = Status(status="idle", label=label)
        await self.update()

    async def on_error(self, message: str):
        self.status = Status(status="error", label=message)
        await self.update()

    async def on_extract_start(self):
        self.status = Status(status="running", label="Extracting Project Plan")
        await self.update()

    async def on_extract_end(self):
        self.status = Status(status="running", label="Extracted Project Plan")
        await self.update()

    async def on_loop_start(self):
        self.status = Status(status="running", label="Loop Started")
        await self.update()

    async def on_iteration_start(self, index: int, task_id: str):
        tasks = self.load_tasks()
        assert tasks is not None
        task = tasks.get_task_by_id(task_id)
        assert task
        label = f"**[Iteration {index + 1} / {self.project.max_iterations}]** **{task.id}** - {task.title}"
        self.status = Status(status="running", label=label, active_task=task_id)
        await self.update()

    async def on_iteration_end(self, index: int, task_id: str):
        tasks = self.load_tasks()
        assert tasks is not None
        task = tasks.get_task_by_id(task_id)
        label = f"Iteration {index} / {self.project.max_iterations}"
        if task:
            result = "PASSED" if task.passes else "FAILED"
            label += f": *{task.id}* - {task.title} ({result})"
        self.status = Status(status="running", label=label, active_task=None)
        await self.update()

    async def on_loop_end(self, iterations: int, completed: bool):
        self.total_iterations = iterations
        if completed:
            if iterations == 0:
                label = "Project completed"
            else:
                label = f"Project completed in {iterations} iterations"
            status = "completed"
        else:
            label = f"Loop finished in {iterations} iterations (*INCOMPLETE*)"
            status = "idle"
        self.status = Status(status=status, label=label)
        await self.update()


class HooksManager:
    def __init__(self, hooks: list[Hooks] | None = None):
        if hooks is None:
            from .notion import NotionHooks

            hooks = [NotionHooks()]
        self.hooks = hooks

    def report_status(self):
        if not self.hooks:
            return
        names = ", ".join(h.name for h in self.hooks)
        rich.print(f" • Hooks: [i]{names}[/]")
        for h in self.hooks:
            h.report_status()

    async def init(self, project: Project):
        for h in self.hooks:
            await h.init(project)

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

    async def on_iteration_start(self, index: int, task_id: str):
        for h in self.hooks:
            await h.on_iteration_start(index, task_id)

    async def on_iteration_end(self, index: int, task_id: str):
        for h in self.hooks:
            await h.on_iteration_end(index, task_id)

    async def on_loop_end(self, iterations: int, completed: bool):
        for h in self.hooks:
            await h.on_loop_end(iterations, completed)
