"""Fetch and resolve Notion comments scoped to the Project Plan section.

The ralpher Notion page is laid out by `ralpher/utils/hooks/notion.md` and
includes a `# 📜 Project Plan` heading. This module finds that heading on the
project's Notion page, collects every block-level comment under it (recursing
into block children), and exposes helpers to render those comments as a
refinement prompt and to mark them resolved when refinement is done.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from znotion import NotionClient
from znotion.models.blocks import ChildPageBlock, Heading1Block
from znotion.models.comments import Comment

from ralpher.models import Project

PROJECT_PLAN_HEADING = "Project Plan"


async def _find_child_page(
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


async def _resolve_page_id(client: NotionClient, title: str) -> str | None:
    """Mirror the resolution rules used by `ralpher/utils/hooks/notion.py`."""
    page_id = os.environ.get("RALPHER_NOTION_PAGE_ID")
    if page_id:
        return page_id
    parent_page_id = os.environ.get("RALPHER_NOTION_PARENT_PAGE_ID")
    if not parent_page_id:
        return None
    return await _find_child_page(client, parent_page_id, title)


@dataclass
class NotionComment:
    """A Notion comment plus the text of the block it was left on."""

    id: str
    discussion_id: str
    text: str
    context: str
    author: str | None


def _rich_text_plain(rich_text: list[Any]) -> str:
    return "".join(getattr(rt, "plain_text", "") or "" for rt in rich_text)


def _block_text(block: Any) -> str:
    """Best-effort extraction of plain text from any block type."""
    data = getattr(block, block.type, None) if hasattr(block, "type") else None
    if not isinstance(data, dict):
        return ""
    rich_text = data.get("rich_text") or []
    parts = [rt.get("plain_text", "") for rt in rich_text if isinstance(rt, dict)]
    return "".join(parts)


def _heading_text(block: Any) -> str:
    return _block_text(block)


async def _iter_section_blocks(
    client: NotionClient, page_id: str
) -> AsyncIterator[Any]:
    """Yield every block under the `# Project Plan` heading until the next H1."""
    in_section = False
    async for block in client.blocks.children(page_id):
        if isinstance(block, Heading1Block):
            title = _heading_text(block)
            if PROJECT_PLAN_HEADING in title:
                in_section = True
                continue
            if in_section:
                return
            continue
        if in_section:
            yield block


async def _collect_comments(
    client: NotionClient, block: Any, out: list[NotionComment]
) -> None:
    context = _block_text(block)
    async for c in client.comments.list(block_id=block.id):
        out.append(
            NotionComment(
                id=c.id,
                discussion_id=c.discussion_id,
                text=_rich_text_plain(c.rich_text),
                context=context,
                author=_comment_author(c),
            )
        )
    if getattr(block, "has_children", False):
        async for child in client.blocks.children(block.id):
            await _collect_comments(client, child, out)


def _comment_author(comment: Comment) -> str | None:
    user = comment.created_by
    if user is None:
        return None
    name = getattr(user, "name", None)
    return name if isinstance(name, str) and name else None


async def fetch_project_plan_comments(project: Project) -> list[NotionComment]:
    """Return every block-level comment under the Project Plan section.

    Returns an empty list if Notion env vars are missing or the page can't be
    resolved, so callers can decide how to surface that to the user.
    """
    token = os.environ.get("RALPHER_NOTION_TOKEN")
    if not token:
        return []

    async with NotionClient(token=token) as client:
        page_id = await _resolve_page_id(client, project.project_dir.name)
        if not page_id:
            return []

        collected: list[NotionComment] = []
        async for block in _iter_section_blocks(client, page_id):
            await _collect_comments(client, block, collected)
        return collected


async def resolve_comments(comments: list[NotionComment]) -> None:
    """Mark each comment resolved.

    Tries the (undocumented) `PATCH /v1/comments/{id}` endpoint first; on
    failure, falls back to posting a reply on the thread so a human can see
    that ralpher handled it.
    """
    if not comments:
        return
    token = os.environ.get("RALPHER_NOTION_TOKEN")
    if not token:
        return
    async with NotionClient(token=token) as client:
        for c in comments:
            await _resolve_one(client, c)


async def _resolve_one(client: NotionClient, comment: NotionComment) -> None:
    try:
        await client._transport.patch(
            f"/comments/{comment.id}", json={"resolved": True}
        )
        return
    except Exception:  # noqa: S110, BLE001 - resolving a comment is best-effort
        pass
    try:
        await client.comments.create(
            discussion_id=comment.discussion_id,
            rich_text=[
                {
                    "type": "text",
                    "text": {"content": "✅ Addressed by ralpher refine."},
                }
            ],
        )
    except Exception:  # noqa: S110, BLE001 - the fallback ack is best-effort
        pass


def render_comments_as_prompt(comments: list[NotionComment]) -> str:
    """Format a list of comments as a refinement prompt for the refine skill."""
    lines = [
        "Refine the Project Plan to address the following comments left on the",
        "Notion page. Each comment is shown alongside the surrounding text it",
        "was attached to. Treat each comment as a concrete change request and",
        "update the plan accordingly.",
        "",
    ]
    for i, c in enumerate(comments, start=1):
        author = f" by {c.author}" if c.author else ""
        context = c.context.strip() or "(no surrounding text — block has no plain text)"
        lines.append(f"## Comment {i}{author}")
        lines.append(f"**On:** {context}")
        lines.append(f"**Comment:** {c.text.strip()}")
        lines.append("")
    return "\n".join(lines)
