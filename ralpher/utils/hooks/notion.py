from pathlib import Path
import os
import httpx
import jinja2

from ralpher.models import Project, ProjectPlan, Status
from ralpher.utils.hooks.hooks import Hooks


async def __create_page(
    parent_page_id: str, title: str, token: str, version: str
) -> str | None:
    url = "https://api.notion.com/v1/pages"
    payload = {
        "parent": {"page_id": parent_page_id},
        "properties": {"title": {"title": [{"text": {"content": title}}]}},
    }
    headers = {
        "Notion-Version": version,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers)
            if response.is_success:
                return response.json()["id"]
            return None
    except Exception:
        return None


async def __find_child_page(
    parent_page_id: str, title: str, token: str, version: str
) -> str | None:
    url = f"https://api.notion.com/v1/blocks/{parent_page_id}/children"
    headers = {
        "Notion-Version": version,
        "Authorization": f"Bearer {token}",
    }
    try:
        async with httpx.AsyncClient() as client:
            cursor = None
            while True:
                params = {"page_size": 100}
                if cursor:
                    params["start_cursor"] = cursor
                response = await client.get(url, headers=headers, params=params)
                if not response.is_success:
                    return None
                data = response.json()
                for block in data.get("results", []):
                    if block.get("type") != "child_page":
                        continue
                    page_title = block.get("child_page", {}).get("title", "")
                    if page_title == title:
                        return block["id"]
                if not data.get("has_more"):
                    break
                cursor = data.get("next_cursor")
    except Exception:
        return None
    return None


async def __resolve_page_id(token: str, version: str, title: str) -> str | None:
    page_id = os.getenv("RALPHER_NOTION_PAGE_ID")
    if page_id:
        return page_id

    parent_page_id = os.getenv("RALPHER_NOTION_PARENT_PAGE_ID")
    if not parent_page_id:
        return None

    existing_id = await __find_child_page(parent_page_id, title, token, version)
    if existing_id:
        os.environ["RALPHER_NOTION_PAGE_ID"] = existing_id
        return existing_id

    new_page_id = await __create_page(parent_page_id, title, token, version)
    if new_page_id:
        os.environ["RALPHER_NOTION_PAGE_ID"] = new_page_id
    return new_page_id


async def __update_page(title: str, content: str) -> bool:
    token = os.environ["RALPHER_NOTION_TOKEN"]
    version = os.getenv("RALPHER_NOTION_VERSION", "2026-03-11")

    page_id = await __resolve_page_id(token, version, title)
    if not page_id:
        return False

    url = f"https://api.notion.com/v1/pages/{page_id}"
    payload = {
        "properties": {"title": {"title": [{"text": {"content": title}}]}},
        "is_locked": True,
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


async def update_notion_page(project: Project, status: Status | None) -> bool:
    if "RALPHER_NOTION_TOKEN" not in os.environ or (
        "RALPHER_NOTION_PAGE_ID" not in os.environ
        and "RALPHER_NOTION_PARENT_PAGE_ID" not in os.environ
    ):
        return False

    project_dir = project.project_dir

    template_file = Path(__file__).parent / "notion.md"
    template_content = template_file.read_text()

    plan = project.load_plan()
    if plan:
        plan.tasks.sort(key=lambda t: t.priority)

    plan_md_file = project_dir / "PLAN.md"
    plan_md = plan_md_file.read_text() if plan_md_file.exists() else "*N/A*"

    promot_md_file = project_dir / "PROMPT.md"
    prompt_md = promot_md_file.read_text() if promot_md_file.exists() else "*N/A*"

    progress_md_file = project_dir / "progress.md"
    progress_md = progress_md_file.read_text() if progress_md_file.exists() else "*N/A*"

    template = jinja2.Template(template_content)
    rendered = template.render(
        plan=plan,
        plan_md=plan_md,
        prompt_md=prompt_md,
        progress_md=progress_md,
        active_task=status.active_task if status else None,
        status=status,
        branch=f"ralph/{project_dir.name[18:]}",
    )
    success = await __update_page(project_dir.name, rendered)
    return success


class NotionHooks(Hooks):
    name = "Notion"

    async def update(self):
        await update_notion_page(self.project, self.status)
