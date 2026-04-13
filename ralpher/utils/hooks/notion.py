import json
from pathlib import Path
import os
import httpx
import jinja2

from ralpher.models import PRD, Status
from ralpher.utils.hooks.hooks import Hooks


async def __update_page(title: str, content: str) -> bool:
    token = os.getenv("NOTION_TOKEN")
    page_id = os.getenv("NOTION_PAGE_ID")
    version = os.getenv("NOTION_VERSION", "2026-03-11")

    url = f"https://api.notion.com/v1/pages/{page_id}"
    payload = {
        "properties": {
            "title": {
                "title": [
                    {
                        "text": {
                            "content": title,
                        }
                    }
                ]
            }
        }
    }
    headers = {
        "Notion-Version": version,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.patch(url, json=payload, headers=headers)
            if not response.is_success:
                return False
    except Exception as e:
        return False

    url = f"https://api.notion.com/v1/pages/{page_id}/markdown"
    payload = {
        "type": "replace_content",
        "replace_content": {"new_str": content, "allow_deleting_content": True},
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.patch(url, json=payload, headers=headers)
            return response.is_success
    except Exception as e:
        # print(f"Error updating Notion page: {e}")
        return False


async def update_notion_page(task_dir: Path, status: Status | None) -> bool:
    if "NOTION_TOKEN" not in os.environ or "NOTION_PAGE_ID" not in os.environ:
        return False

    template_file = Path(__file__).parent / "notion.md"
    template_content = template_file.read_text()

    prd_file = task_dir / "prd.json"
    prd = PRD.load(prd_file) if prd_file.exists() else None
    if prd:
        prd.user_stories.sort(key=lambda us: us.priority)

    prd_md_file = task_dir / "PRD.md"
    prd_md = prd_md_file.read_text() if prd_md_file.exists() else "*N/A*"

    promot_md_file = task_dir / "PROMPT.md"
    prompt_md = promot_md_file.read_text() if promot_md_file.exists() else "*N/A*"

    progress_md_file = task_dir / "progress.md"
    progress_md = progress_md_file.read_text() if progress_md_file.exists() else "*N/A*"

    template = jinja2.Template(template_content)
    rendered = template.render(
        prd=prd,
        prd_md=prd_md,
        prompt_md=prompt_md,
        progress_md=progress_md,
        active_us=status.active_user_story if status else None,
        status=status,
    )
    success = await __update_page(task_dir.name, rendered)
    return success


class NotionHooks(Hooks):
    async def update(self):
        await update_notion_page(self.task_dir, self.status)
