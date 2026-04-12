from pathlib import Path
import json
from typing import Literal
import datetime
import socket
import os
import dotenv

from ..models import PRD


class Hooks:
    def __init__(self, task_id: str, task_dir: Path, max_iterations: int):
        self.task_id = task_id
        self.task_dir = task_dir
        self.max_iterations = max_iterations
        self.start_time = datetime.datetime.now()
        dotenv.load_dotenv()  # Load environment variables from .env file
        self.project = os.getenv("RALPHER_PROJECT", "ralpher")

    def load_prd(self) -> PRD:
        prd_file = self.task_dir / "prd.json"
        if not prd_file.exists():
            raise FileNotFoundError(f"{prd_file} not found.")
        return PRD.model_validate(json.loads(prd_file.read_text()))

    async def on_extract_start(self): ...

    async def on_extract_end(self, success: bool): ...

    async def on_loop_start(self): ...

    async def on_iteration_start(self, index: int): ...

    async def on_iteration_end(self, index: int): ...

    async def on_loop_end(
        self,
        iterations: int,
        status: Literal["complete", "incomplete", "crashed", "canceled"],
    ): ...
