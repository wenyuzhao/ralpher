import os
from pathlib import Path

import jinja2
import rich
from znotion import NotionClient
from znotion.models import ChildPageBlock

from ralpher.models import Project, Status
from ralpher.utils.hooks.hooks import Hooks


async def __create_page(
    client: NotionClient, parent_page_id: str, title: str
) -> str | None:
    try:
        page = await client.pages.create(
            parent={"page_id": parent_page_id},
            properties={"title": {"title": [{"text": {"content": title}}]}},
        )
        return page.id
    except Exception:  # noqa: BLE001 - Notion sync is optional; degrade to no page
        return None


async def __find_child_page(
    client: NotionClient, parent_page_id: str, title: str
) -> str | None:
    try:
        async for block in client.blocks.children(parent_page_id):
            if (
                isinstance(block, ChildPageBlock)
                and block.child_page.get("title") == title
            ):
                return block.id
    except Exception:  # noqa: BLE001 - Notion sync is optional; degrade to no page
        return None
    return None


async def __resolve_page_id(client: NotionClient, title: str) -> str | None:
    page_id = os.getenv("RALPHER_NOTION_PAGE_ID")
    if page_id:
        return page_id

    parent_page_id = os.getenv("RALPHER_NOTION_PARENT_PAGE_ID")
    if not parent_page_id:
        return None

    existing_id = await __find_child_page(client, parent_page_id, title)
    if existing_id:
        os.environ["RALPHER_NOTION_PAGE_ID"] = existing_id
        return existing_id

    new_page_id = await __create_page(client, parent_page_id, title)
    if new_page_id:
        os.environ["RALPHER_NOTION_PAGE_ID"] = new_page_id
    return new_page_id


async def __update_page(title: str, content: str) -> tuple[bool, str | None]:
    token = os.environ["RALPHER_NOTION_TOKEN"]
    # Workaround to bypass Cloudflare's stupid security checks
    content = content.replace("`python", "`python\u200e")

    try:
        async with NotionClient(token=token) as client:
            page_id = await __resolve_page_id(client, title)
            if not page_id:
                return False, None

            await client.pages.update(
                page_id,
                properties={"title": {"title": [{"text": {"content": title}}]}},
                is_locked=True,
            )

            await client.pages.replace_markdown(
                page_id,
                content,
                allow_deleting_content=True,
            )
            # Add dash to page_id
            page_id = page_id.replace("-", "")
            return True, f"https://notion.so/{page_id}"
    except Exception:  # noqa: BLE001 - Notion sync is optional; degrade to no page
        return False, None


async def update_notion_page(project: Project, status: Status | None) -> str | None:
    if "RALPHER_NOTION_TOKEN" not in os.environ or (
        "RALPHER_NOTION_PAGE_ID" not in os.environ
        and "RALPHER_NOTION_PARENT_PAGE_ID" not in os.environ
    ):
        return None

    project_dir = project.project_dir

    template_file = Path(__file__).parent / "notion.md"
    template_content = template_file.read_text()

    config = project.load_config()
    branch = config.target_branch if config else "N/A"
    tasks = project.load_tasks()

    plan_md_file = project_dir / "PLAN.md"
    plan_md = plan_md_file.read_text() if plan_md_file.exists() else "*N/A*"

    promot_md_file = project_dir / "PROMPT.md"
    prompt_md = promot_md_file.read_text() if promot_md_file.exists() else "*N/A*"

    progress_md_file = project_dir / "progress.md"
    progress_md = progress_md_file.read_text() if progress_md_file.exists() else "*N/A*"

    template = jinja2.Template(template_content)
    rendered = template.render(
        tasks=tasks.tasks if tasks else None,
        plan_md=plan_md,
        prompt_md=prompt_md,
        progress_md=progress_md,
        active_task=status.active_task if status else None,
        status=status,
        branch=branch,
    )
    _success, page_id = await __update_page(project_dir.name, rendered)
    return page_id


class NotionHooks(Hooks):
    name = "Notion"
    url: str | None = None

    async def update(self):
        url = await update_notion_page(self.project, self.status)
        if not self.url and url:
            self.url = url

    def report_status(self):
        rich.print(f" • Tracking link: [i][u]{self.url}[/][/]")
