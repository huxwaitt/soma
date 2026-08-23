"""MCP tool wrappers for mail."""

from __future__ import annotations

from typing import Annotated, Optional

from mcp.types import CallToolResult
from pydantic import Field

from outlook_mcp.client import attachments as attachments_client
from outlook_mcp.client import mail as mail_client
from outlook_mcp.ui import ui_meta, ui_result
from outlook_mcp.utils.formatting import format_response
from outlook_mcp.utils.safety import safe_call

# Module-level so FastMCP can resolve them: with ``from __future__ import
# annotations`` every hint is a string evaluated against module globals,
# so aliases defined inside register() would raise InvalidSignature.
EntryIds = Annotated[
    list[str],
    Field(min_length=1, max_length=500, description="EntryIDs to operate on (1-500)."),
]
StopOnError = Annotated[
    bool,
    Field(description="Abort the batch at the first failure instead of continuing."),
]
ConversationEntryId = Annotated[
    str,
    Field(min_length=1, description="EntryID of any mail in the thread (from list/search/get_mail)."),
]
ConversationIncludeBody = Annotated[
    bool,
    Field(description="Include each mail's plain-text body (off by default; summaries carry a 200-char preview)."),
]
ConversationMaxBodyChars = Annotated[
    int,
    Field(ge=0, description="Per-mail body truncation when include_body=True (0 = no limit)."),
]
ConversationLimit = Annotated[
    int,
    Field(ge=1, le=500, description="Max mails to return, oldest first."),
]
TrimQuoted = Annotated[
    bool,
    Field(
        description=(
            "Also return body_trimmed / trimmed_chars / trim_markers: the body "
            "with quoted history (Outlook/Gmail/OWA headers, '>' blocks) and "
            "the signature cut off. body itself is unchanged."
        ),
    ),
]
Fields = Annotated[
    Optional[list[str]],
    Field(
        description=(
            "Keep only these keys on each returned item (entry_id is always kept; "
            "unknown names are ignored). Omit for the full shape."
        ),
    ),
]
PreviewChars = Annotated[
    int,
    Field(ge=0, le=5000, description="Length of each item's preview; 0 leaves preview out."),
]


def register(mcp, bridge) -> None:
    @mcp.tool(
        name="outlook_list_mails",
        annotations={
            "title": "List Outlook mails",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        meta=ui_meta("mail-list"),
        structured_output=False,
    )
    @safe_call
    async def outlook_list_mails(
        folder: Annotated[
            str,
            Field(
                description=(
                    "Folder name. Either a well-known name (inbox, sent, drafts, "
                    "deleted, junk) or a path like 'Inbox/Projects/Quinn'."
                ),
            ),
        ] = "inbox",
        limit: Annotated[int, Field(ge=1, le=100, description="Max items.")] = 25,
        offset: Annotated[int, Field(ge=0, description="Pagination offset.")] = 0,
        unread_only: Annotated[bool, Field(description="Return only unread.")] = False,
        since: Annotated[Optional[str], Field(description="ISO-8601 lower bound on ReceivedTime.")] = None,
        until: Annotated[Optional[str], Field(description="ISO-8601 upper bound on ReceivedTime.")] = None,
        from_address: Annotated[Optional[str], Field(description="Substring match on sender email (resolved to SMTP, filtered server-side).")] = None,
        has_attachments: Annotated[Optional[bool], Field(description="True = only mails with attachments, False = only without, None = any.")] = None,
        fields: Fields = None,
        preview_chars: PreviewChars = 200,
        response_format: Annotated[str, Field(description="'markdown' or 'json'.")] = "markdown",
    ) -> CallToolResult:
        """List mail items from a folder, newest first. All filters are pushed into Outlook's index (DASL Restrict), so large folders stay fast."""
        data = await bridge.call(
            mail_client.list_mails,
            folder=folder,
            limit=limit,
            offset=offset,
            unread_only=unread_only,
            since=since,
            until=until,
            from_address=from_address,
            has_attachments=has_attachments,
            fields=fields,
            preview_chars=preview_chars,
        )
        return ui_result(format_response(data, response_format), data)

    @mcp.tool(
        name="outlook_search_mails",
        annotations={
            "title": "Search Outlook mails",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        meta=ui_meta("mail-list"),
        structured_output=False,
    )
    @safe_call
    async def outlook_search_mails(
        query: Annotated[str, Field(min_length=1, description="Search keywords or DASL filter.")],
        folder: Annotated[str, Field(description="Folder to search in.")] = "inbox",
        scope: Annotated[
            str,
            Field(
                description=(
                    "Where to look: 'subject_body' (default), 'subject', 'from', "
                    "or 'dasl' to pass `query` as a raw DASL @SQL filter."
                ),
            ),
        ] = "subject_body",
        limit: Annotated[int, Field(ge=1, le=100)] = 25,
        since: Annotated[Optional[str], Field(description="ISO-8601 lower bound on ReceivedTime (ignored for scope='dasl').")] = None,
        until: Annotated[Optional[str], Field(description="ISO-8601 upper bound on ReceivedTime (ignored for scope='dasl').")] = None,
        unread_only: Annotated[bool, Field(description="Return only unread (ignored for scope='dasl').")] = False,
        has_attachments: Annotated[Optional[bool], Field(description="Filter on attachment presence (ignored for scope='dasl').")] = None,
        fields: Fields = None,
        preview_chars: PreviewChars = 200,
        response_format: Annotated[str, Field(description="'markdown' or 'json'.")] = "markdown",
    ) -> CallToolResult:
        """Search a mail folder by subject, body, or sender. Keyword + date/unread/attachment filters are combined into one server-side DASL Restrict."""
        data = await bridge.call(
            mail_client.search_mails,
            query=query,
            folder=folder,
            limit=limit,
            scope=scope,
            since=since,
            until=until,
            unread_only=unread_only,
            has_attachments=has_attachments,
            fields=fields,
            preview_chars=preview_chars,
        )
        return ui_result(format_response(data, response_format), data)

    @mcp.tool(
        name="outlook_search_attachments",
        annotations={
            "title": "Find Outlook mails by attachment filename",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    @safe_call
    async def outlook_search_attachments(
        query: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "Words that must all appear in the attachment filename (any order, "
                    "case-insensitive), or a glob like '*.pdf' / 'budget*.xlsx' when it "
                    "contains * or ?."
                ),
            ),
        ],
        folder: Annotated[str, Field(description="Folder to start in (well-known name or path).")] = "inbox",
        since: Annotated[Optional[str], Field(description="ISO-8601 lower bound on ReceivedTime.")] = None,
        limit: Annotated[int, Field(ge=1, le=200, description="Max mails to return.")] = 50,
        include_subfolders: Annotated[bool, Field(description="Also walk every folder below `folder`.")] = True,
        fields: Fields = None,
    ) -> str:
        """Find mails whose attachment filenames match. Only mails with attachments are read; inline images are ignored. Returns mail summaries newest-first, each with the matching attachments (index, filename, size)."""
        data = await bridge.call(
            mail_client.search_attachments,
            query=query,
            folder=folder,
            since=since,
            limit=limit,
            include_subfolders=include_subfolders,
            fields=fields,
        )
        return format_response(data, "json")

    @mcp.tool(
        name="outlook_advanced_search",
        annotations={
            "title": "Indexed search across all Outlook folders (Windows Search)",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    @safe_call
    async def outlook_advanced_search(
        query: Annotated[
            str,
            Field(min_length=1, description="Words that must all match (index phrase match) in subject, body, or indexed attachment text."),
        ],
        scope: Annotated[
            str,
            Field(description="'all' = every store (mailboxes, archives, PSTs), or one folder path to search with its sub-folders."),
        ] = "all",
        since: Annotated[Optional[str], Field(description="ISO-8601 lower bound on ReceivedTime.")] = None,
        limit: Annotated[int, Field(ge=1, le=200, description="Max mails to return, newest first.")] = 50,
        timeout_sec: Annotated[int, Field(ge=1, le=55, description="How long to wait for the index before returning what has arrived.")] = 20,
        fields: Fields = None,
    ) -> str:
        """Search every folder at once through Outlook's Windows Search index (Application.AdvancedSearch). Matches attachment contents when the store is indexed. Returns mail summaries newest-first plus timed_out."""
        data = await bridge.call(
            mail_client.advanced_search,
            query=query,
            scope=scope,
            since=since,
            limit=limit,
            timeout_sec=timeout_sec,
            fields=fields,
        )
        return format_response(data, "json")

    @mcp.tool(
        name="outlook_extract_attachment_text",
        annotations={
            "title": "Read the text of one Outlook attachment",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    @safe_call
    async def outlook_extract_attachment_text(
        entry_id: Annotated[str, Field(min_length=1, description="EntryID of the mail.")],
        index: Annotated[int, Field(ge=1, description="1-indexed attachment (from get_mail.attachments[].index).")],
        max_chars: Annotated[int, Field(ge=0, description="Truncate the text beyond this many chars (0 = no limit).")] = 20000,
    ) -> str:
        """Extract plain text from a .pdf, .docx, .xlsx, .pptx, .txt, .csv or .md attachment. The file is saved to a temporary folder under the user profile and deleted again. PDF and Excel need the optional 'search' extra."""
        data = await bridge.call(
            attachments_client.extract_attachment_text,
            entry_id=entry_id,
            index=index,
            max_chars=max_chars,
        )
        return format_response(data, "json")

    @mcp.tool(
        name="outlook_get_mail",
        annotations={
            "title": "Get full Outlook mail",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        meta=ui_meta("mail-view"),
        structured_output=False,
    )
    @safe_call
    async def outlook_get_mail(
        entry_id: Annotated[str, Field(min_length=1, description="EntryID of the mail item.")],
        include_body: Annotated[bool, Field(description="Include the plain-text body.")] = True,
        include_html: Annotated[
            bool,
            Field(
                description=(
                    "Also include the raw HTML body. Off by default — it is "
                    "usually huge and rarely needed; the plain-text body "
                    "carries the same content."
                ),
            ),
        ] = False,
        max_body_chars: Annotated[
            int,
            Field(
                ge=0,
                description="Truncate the body beyond this many chars (0 = no limit).",
            ),
        ] = 10000,
        trim_quoted: TrimQuoted = False,
        fields: Fields = None,
        response_format: Annotated[str, Field(description="'markdown' or 'json'.")] = "markdown",
    ) -> CallToolResult:
        """Fetch body, headers, and attachment list for one mail item.

        If the response has body_truncated=true, re-call with a higher
        max_body_chars to read more.
        """
        data = await bridge.call(
            mail_client.get_mail,
            entry_id=entry_id,
            include_body=include_body,
            include_html=include_html,
            max_body_chars=max_body_chars,
            trim_quoted=trim_quoted,
            fields=fields,
        )
        return ui_result(format_response(data, response_format), data)

    @mcp.tool(
        name="outlook_get_conversation",
        annotations={
            "title": "Get the whole Outlook conversation (thread) for a mail",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    @safe_call
    async def outlook_get_conversation(
        entry_id: ConversationEntryId,
        include_body: ConversationIncludeBody = False,
        max_body_chars: ConversationMaxBodyChars = 2000,
        limit: ConversationLimit = 200,
        trim_quoted: TrimQuoted = False,
        fields: Fields = None,
        preview_chars: PreviewChars = 200,
    ) -> str:
        """Return every mail in the thread containing entry_id, oldest first, across folders (Inbox, Sent Items, sub-folders). Use before replying so the reply is grounded in the full exchange."""
        data = await bridge.call(
            mail_client.get_conversation,
            entry_id=entry_id,
            include_body=include_body,
            max_body_chars=max_body_chars,
            limit=limit,
            trim_quoted=trim_quoted,
            fields=fields,
            preview_chars=preview_chars,
        )
        return format_response(data, "json")

    @mcp.tool(
        name="outlook_send_mail",
        annotations={
            "title": "Send Outlook mail",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    @safe_call
    async def outlook_send_mail(
        to: Annotated[list[str], Field(min_length=1, description="Recipient addresses.")],
        subject: Annotated[str, Field(description="Subject line.")],
        body: Annotated[str, Field(description="Message body. Plain text unless html=True.")],
        cc: Annotated[Optional[list[str]], Field(description="CC recipients.")] = None,
        bcc: Annotated[Optional[list[str]], Field(description="BCC recipients.")] = None,
        html: Annotated[bool, Field(description="Treat body as HTML.")] = False,
        attachments: Annotated[Optional[list[str]], Field(description="Absolute paths to local files.")] = None,
        importance: Annotated[str, Field(description="One of: 'low', 'normal', 'high'.")] = "normal",
        save_only: Annotated[bool, Field(description="If true, save to Drafts instead of sending.")] = False,
    ) -> str:
        """Compose and send a new mail. Set save_only=True to save to Drafts."""
        data = await bridge.call(
            mail_client.send_mail,
            to=to,
            subject=subject,
            body=body,
            cc=cc,
            bcc=bcc,
            html=html,
            attachments=attachments,
            importance=importance,
            save_only=save_only,
        )
        return format_response(data, "json")

    @mcp.tool(
        name="outlook_reply_mail",
        annotations={
            "title": "Reply to Outlook mail",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    @safe_call
    async def outlook_reply_mail(
        entry_id: Annotated[str, Field(description="EntryID of the mail to reply to.")],
        body: Annotated[str, Field(description="Reply body. Quoted original is appended.")],
        reply_all: Annotated[bool, Field(description="Reply to all recipients.")] = False,
        html: Annotated[bool, Field(description="Treat body as HTML.")] = False,
        attachments: Annotated[Optional[list[str]], Field(description="Files to attach.")] = None,
        save_only: Annotated[bool, Field(description="If true, save the reply to Drafts (threaded under the original) instead of sending.")] = False,
    ) -> str:
        """Reply (or reply-all) to an existing mail. Set save_only=True to save the reply to Drafts instead of sending."""
        data = await bridge.call(
            mail_client.reply_mail,
            entry_id=entry_id,
            body=body,
            reply_all=reply_all,
            html=html,
            attachments=attachments,
            save_only=save_only,
        )
        return format_response(data, "json")

    @mcp.tool(
        name="outlook_forward_mail",
        annotations={
            "title": "Forward Outlook mail",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    @safe_call
    async def outlook_forward_mail(
        entry_id: Annotated[str, Field(description="EntryID of the mail to forward.")],
        to: Annotated[list[str], Field(min_length=1, description="Forward recipients.")],
        body: Annotated[str, Field(description="Optional note above the forwarded mail.")] = "",
        cc: Annotated[Optional[list[str]], Field(description="CC recipients.")] = None,
        html: Annotated[bool, Field(description="Treat body as HTML.")] = False,
        save_only: Annotated[bool, Field(description="If true, save the forward to Drafts instead of sending.")] = False,
    ) -> str:
        """Forward an existing mail with an optional added note. Set save_only=True to save to Drafts instead of sending."""
        data = await bridge.call(
            mail_client.forward_mail,
            entry_id=entry_id,
            to=to,
            body=body,
            cc=cc,
            html=html,
            save_only=save_only,
        )
        return format_response(data, "json")

    @mcp.tool(
        name="outlook_move_mail",
        annotations={
            "title": "Move Outlook mail to folder",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    @safe_call
    async def outlook_move_mail(
        entry_id: Annotated[str, Field(description="EntryID of the mail to move.")],
        target_folder: Annotated[str, Field(description="Destination folder.")],
    ) -> str:
        """Move a mail to another folder. Returns the new EntryID."""
        data = await bridge.call(
            mail_client.move_mail, entry_id=entry_id, target_folder=target_folder
        )
        return format_response(data, "json")

    @mcp.tool(
        name="outlook_delete_mail",
        annotations={
            "title": "Delete Outlook mail (move to Deleted Items)",
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    @safe_call
    async def outlook_delete_mail(
        entry_id: Annotated[str, Field(description="EntryID of the mail to delete.")],
    ) -> str:
        """Delete a mail (Outlook moves it to Deleted Items)."""
        data = await bridge.call(mail_client.delete_mail, entry_id=entry_id)
        return format_response(data, "json")

    @mcp.tool(
        name="outlook_mark_mail",
        annotations={
            "title": "Mark Outlook mail read/unread or flag it",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    @safe_call
    async def outlook_mark_mail(
        entry_id: Annotated[str, Field(description="EntryID of the mail.")],
        read: Annotated[Optional[bool], Field(description="True=mark read, False=unread, None=no change.")] = None,
        flagged: Annotated[Optional[bool], Field(description="True=flag for follow-up, False=clear flag.")] = None,
    ) -> str:
        """Toggle read state and/or follow-up flag on a mail."""
        data = await bridge.call(
            mail_client.mark_mail, entry_id=entry_id, read=read, flagged=flagged
        )
        return format_response(data, "json")

    @mcp.tool(
        name="outlook_save_attachments",
        annotations={
            "title": "Save Outlook mail attachments to disk",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    @safe_call
    async def outlook_save_attachments(
        entry_id: Annotated[str, Field(description="EntryID of the mail.")],
        output_dir: Annotated[str, Field(description="Absolute directory under your user profile.")],
        attachment_index: Annotated[
            Optional[int], Field(ge=1, description="1-indexed attachment. Omit to save all.")
        ] = None,
    ) -> str:
        """Save one or all attachments from a mail to a local directory."""
        data = await bridge.call(
            mail_client.save_attachments,
            entry_id=entry_id,
            output_dir=output_dir,
            attachment_index=attachment_index,
        )
        return format_response(data, "json")

    # ------------------------------------------------------------------
    # Bulk operations
    # ------------------------------------------------------------------

    @mcp.tool(
        name="outlook_bulk_move_mails",
        annotations={
            "title": "Move many Outlook mails to a folder",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    @safe_call
    async def outlook_bulk_move_mails(
        entry_ids: EntryIds,
        target_folder: Annotated[str, Field(description="Destination folder.")],
        stop_on_error: StopOnError = False,
    ) -> str:
        """Move many mails in one call. Returns per-item results and failures; stale ids are reported, not fatal."""
        data = await bridge.call(
            mail_client.bulk_move_mails,
            entry_ids=entry_ids,
            target_folder=target_folder,
            stop_on_error=stop_on_error,
        )
        return format_response(data, "json")

    @mcp.tool(
        name="outlook_bulk_delete_mails",
        annotations={
            "title": "Delete many Outlook mails (move to Deleted Items)",
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    @safe_call
    async def outlook_bulk_delete_mails(
        entry_ids: EntryIds,
        stop_on_error: StopOnError = False,
    ) -> str:
        """Delete many mails in one call (Outlook moves them to Deleted Items)."""
        data = await bridge.call(
            mail_client.bulk_delete_mails,
            entry_ids=entry_ids,
            stop_on_error=stop_on_error,
        )
        return format_response(data, "json")

    @mcp.tool(
        name="outlook_bulk_mark_mails",
        annotations={
            "title": "Mark/flag/categorize many Outlook mails",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    @safe_call
    async def outlook_bulk_mark_mails(
        entry_ids: EntryIds,
        read: Annotated[Optional[bool], Field(description="True=mark read, False=unread, None=no change.")] = None,
        flagged: Annotated[Optional[bool], Field(description="True=flag, False=clear flag, None=no change.")] = None,
        categories: Annotated[
            Optional[list[str]],
            Field(description="Replace the category list (empty list clears). None=no change."),
        ] = None,
        stop_on_error: StopOnError = False,
    ) -> str:
        """Set read state, flag, and/or categories on many mails in one call."""
        data = await bridge.call(
            mail_client.bulk_mark_mails,
            entry_ids=entry_ids,
            read=read,
            flagged=flagged,
            categories=categories,
            stop_on_error=stop_on_error,
        )
        return format_response(data, "json")

    # ------------------------------------------------------------------
    # Export / save-as
    # ------------------------------------------------------------------

    @mcp.tool(
        name="outlook_export_mails",
        annotations={
            "title": "Export Outlook mail metadata to CSV/JSON",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    @safe_call
    async def outlook_export_mails(
        output_path: Annotated[
            str,
            Field(description="Absolute .csv or .json path under your user profile. Parent dirs are created."),
        ],
        entry_ids: Annotated[
            Optional[list[str]],
            Field(max_length=2000, description="Explicit EntryIDs to export. If given, folder/filters are ignored."),
        ] = None,
        folder: Annotated[str, Field(description="Folder to export from.")] = "inbox",
        limit: Annotated[int, Field(ge=1, le=10000, description="Max rows when exporting by folder.")] = 1000,
        unread_only: Annotated[bool, Field(description="Only unread.")] = False,
        since: Annotated[Optional[str], Field(description="ISO-8601 lower bound on ReceivedTime.")] = None,
        until: Annotated[Optional[str], Field(description="ISO-8601 upper bound on ReceivedTime.")] = None,
        from_address: Annotated[Optional[str], Field(description="Substring match on sender SMTP address.")] = None,
        has_attachments: Annotated[Optional[bool], Field(description="Filter on attachment presence.")] = None,
        include_body: Annotated[bool, Field(description="Add a plain-text body column.")] = False,
        max_body_chars: Annotated[int, Field(ge=0, description="Truncate body column (0 = no limit).")] = 2000,
        fmt: Annotated[str, Field(description="'csv' (Excel-friendly, UTF-8 BOM) or 'json'.")] = "csv",
    ) -> str:
        """Write mail metadata (sender SMTP, subject, dates, flags, categories...) to a file for Excel / pandas / Power Automate. Returns the path and row count, not the rows."""
        data = await bridge.call(
            mail_client.export_mails,
            output_path=output_path,
            entry_ids=entry_ids,
            folder=folder,
            limit=limit,
            unread_only=unread_only,
            since=since,
            until=until,
            from_address=from_address,
            has_attachments=has_attachments,
            include_body=include_body,
            max_body_chars=max_body_chars,
            fmt=fmt,
        )
        return format_response(data, "json")

    @mcp.tool(
        name="outlook_save_mail_as",
        annotations={
            "title": "Save an Outlook mail to disk (.msg/.txt/.html)",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    @safe_call
    async def outlook_save_mail_as(
        entry_id: Annotated[str, Field(min_length=1, description="EntryID of the mail.")],
        output_dir: Annotated[str, Field(description="Absolute directory under your user profile.")],
        fmt: Annotated[str, Field(description="'msg' (full fidelity, re-openable in Outlook), 'txt', or 'html'.")] = "msg",
        filename: Annotated[
            Optional[str],
            Field(description="Bare file name (no path). Defaults to a sanitized subject. Never overwrites — uniquified with (n)."),
        ] = None,
    ) -> str:
        """Save a single mail as a file. Use .msg to archive with attachments and headers intact."""
        data = await bridge.call(
            mail_client.save_mail_as,
            entry_id=entry_id,
            output_dir=output_dir,
            fmt=fmt,
            filename=filename,
        )
        return format_response(data, "json")
