"""MCP tool wrappers for free/busy and meeting-time search."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from outlook_mcp.client import freebusy as fb_client
from outlook_mcp.utils.formatting import format_response
from outlook_mcp.utils.safety import safe_call


def register(mcp, bridge) -> None:
    @mcp.tool(
        name="outlook_get_free_busy",
        annotations={
            "title": "Get free/busy for people",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    @safe_call
    async def outlook_get_free_busy(
        addresses: Annotated[list[str], Field(description="SMTP addresses (max 20).", min_length=1, max_length=20)],
        start: Annotated[str, Field(description="ISO-8601 start of the window.")],
        end: Annotated[str, Field(description="ISO-8601 end of the window (max 62 days after start).")],
        interval_minutes: Annotated[int, Field(ge=1, le=1440, description="Slot granularity in minutes.")] = 30,
        busy_blocks_only: Annotated[
            bool,
            Field(description="Return only the merged busy_blocks per person (default). False adds the per-slot slots[] array."),
        ] = True,
    ) -> str:
        """Free/busy per person (Exchange only). Returns JSON: people[].busy_blocks (plus people[].slots when busy_blocks_only=false), unknown[]."""
        data = await bridge.call(
            fb_client.get_free_busy,
            addresses=addresses,
            start=start,
            end=end,
            interval_minutes=interval_minutes,
            busy_blocks_only=busy_blocks_only,
        )
        return format_response(data, "json")

    @mcp.tool(
        name="outlook_find_meeting_times",
        annotations={
            "title": "Find meeting times",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    @safe_call
    async def outlook_find_meeting_times(
        addresses: Annotated[list[str], Field(description="Attendee SMTP addresses (max 20 incl. yourself).")],
        start: Annotated[str, Field(description="ISO-8601 start of the search window.")],
        end: Annotated[str, Field(description="ISO-8601 end of the search window (max 62 days).")],
        duration_minutes: Annotated[int, Field(ge=1, le=1440)],
        work_start: Annotated[str, Field(description="'HH:MM' local.")] = "09:00",
        work_end: Annotated[str, Field(description="'HH:MM' local.")] = "17:00",
        buffer_minutes: Annotated[int, Field(ge=0, le=240, description="Required free margin either side.")] = 0,
        weekdays_only: Annotated[bool, Field()] = True,
        include_self: Annotated[bool, Field(description="Also require the current user to be free.")] = True,
        max_results: Annotated[int, Field(ge=1, le=100)] = 10,
        include_slots: Annotated[
            bool,
            Field(description="Also return people[] with each person's slots and busy_blocks. Off by default; the candidates are usually all you need."),
        ] = False,
    ) -> str:
        """Candidate meeting times when everyone with free/busy data is free. Returns JSON sorted by start."""
        data = await bridge.call(
            fb_client.find_meeting_times,
            addresses=addresses,
            start=start,
            end=end,
            duration_minutes=duration_minutes,
            work_start=work_start,
            work_end=work_end,
            buffer_minutes=buffer_minutes,
            weekdays_only=weekdays_only,
            include_self=include_self,
            max_results=max_results,
            include_slots=include_slots,
        )
        return format_response(data, "json")
