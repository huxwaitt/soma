"""MCP tool wrappers for workflows computed in code (read-only, JSON only)."""

from __future__ import annotations

from typing import Annotated, Optional

from pydantic import Field

from outlook_mcp.client import workflows as wf_client
from outlook_mcp.utils.formatting import format_response
from outlook_mcp.utils.safety import safe_call

_READ_ONLY = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}


def register(mcp, bridge) -> None:
    @mcp.tool(
        name="outlook_awaiting_reply",
        annotations={"title": "Sent threads nobody has answered", **_READ_ONLY},
    )
    @safe_call
    async def outlook_awaiting_reply(
        days: Annotated[int, Field(ge=0, le=365, description="How long a thread must have been quiet to count.")] = 3,
        since_days: Annotated[int, Field(ge=1, le=365, description="How far back to read the sent folder.")] = 30,
        limit: Annotated[int, Field(ge=1, le=200, description="Max threads to return, longest wait first.")] = 50,
        folder: Annotated[str, Field(description="Folder holding the user's sent mail.")] = "sent",
    ) -> str:
        """Threads where the user's mail is the newest item, older than `days`, and went to somebody else. Groups sent mail by conversation (at most 60 newest threads) and returns only the waiting ones with the last line the user wrote."""
        data = await bridge.call(
            wf_client.awaiting_reply,
            days=days,
            since_days=since_days,
            limit=limit,
            folder=folder,
        )
        return format_response(data, "json")

    @mcp.tool(
        name="outlook_find",
        annotations={"title": "Find a mail from people, words and dates", **_READ_ONLY},
    )
    @safe_call
    async def outlook_find(
        people: Annotated[Optional[list[str]], Field(description="Names or addresses to match on the sender (one 'from' search each).")] = None,
        words: Annotated[Optional[list[str]], Field(description="Topic words (one subject/body search each).")] = None,
        since: Annotated[Optional[str], Field(description="ISO-8601 lower bound on ReceivedTime.")] = None,
        until: Annotated[Optional[str], Field(description="ISO-8601 upper bound on ReceivedTime.")] = None,
        folders: Annotated[Optional[list[str]], Field(description="Folders to search, in order. Default ['inbox', 'sent'].")] = None,
        include_subfolders: Annotated[bool, Field(description="Also walk every folder below each listed folder.")] = False,
        limit: Annotated[int, Field(ge=1, le=50, description="Max threads to return, best score first.")] = 10,
    ) -> str:
        """Run the find search plan in code: per folder, a sender search per person and a subject/body search per word; merge, one mail per conversation, score (person +3, word in subject +2, word in body +1 for the top 20, date fit +1), and return the best threads with the sentence that holds the most query words."""
        data = await bridge.call(
            wf_client.find,
            people=people,
            words=words,
            since=since,
            until=until,
            folders=folders,
            include_subfolders=include_subfolders,
            limit=limit,
        )
        return format_response(data, "json")

    @mcp.tool(
        name="outlook_voice_sample",
        annotations={"title": "Sample the user's own writing from sent mail", **_READ_ONLY},
    )
    @safe_call
    async def outlook_voice_sample(
        address: Annotated[Optional[str], Field(description="Sample mails sent to this address when at least 3 exist; otherwise the newest sent mails overall.")] = None,
        n: Annotated[int, Field(ge=1, le=50, description="How many sent mails to sample.")] = 10,
        max_chars: Annotated[int, Field(ge=50, le=5000, description="Length of each opening excerpt.")] = 300,
    ) -> str:
        """Openings (first max_chars of the trimmed body) and closings (last two lines) of the user's sent mail, plus greeting and sign-off counts and the average length. Quoted history and signatures are removed first."""
        data = await bridge.call(
            wf_client.voice_sample,
            address=address,
            n=n,
            max_chars=max_chars,
        )
        return format_response(data, "json")
