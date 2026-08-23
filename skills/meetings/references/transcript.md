# Transcript reference — pasted transcripts in `/administrator:notes`

Sometimes what the user pastes is not notes but a transcript: the speaker-by-speaker record from `references/copilot-transcript-prompt.md`, a Teams export, or the same shape typed by hand. This page holds only two things: how to tell, and what `vault_attach_transcript` does with it. Everything else (finding the meeting, decisions, action items, waiting items, `status: held`, `last_contact`, the minutes email, the report) is "Half 2 — notes" in `SKILL.md`.

## 1. Is it a transcript?

Treat the pasted text (or the file the user named) as a transcript when either holds:

- at least 5 lines match `^\[?\d{0,2}:?\d{0,2}\]?\s*[A-Z][^:]{1,40}: ` (a clock in square brackets or nothing, then a name starting with a capital, a colon and a space: `[13:02] Jane Doe: …`, `Jane Doe: …`), or at least 5 lines match `^\d{1,3}[.)]\s+[A-Z][^:]{1,40}: ` (Copilot sometimes numbers the turns: `12. Jane Doe: …`);
- or one line is exactly `END OF TRANSCRIPT`.

The user's own words win over the rule: "here is the transcript" means transcript even with four turns; "these are my notes" means notes even if every line starts with a name. Say which one you took in the report. Plain notes go through the normal steps and this page does not apply.

The server uses the same two patterns (`_TURN_RE`, `_TURN_NUMBERED_RE` in `administrator_vault/workflows.py`); a line that matches neither is kept as a wrapped line of the turn above it and is not counted.

## 2. What `vault_attach_transcript` does

Input: `meeting_path` (the meeting note, vault-relative) and `transcript_path` (a file under `Administrator/Attachments/`, written once by the host's Write tool with the text exactly as pasted or read — anything above the first turn line included). The server then:

1. Drops a trailing `Speakers:` block (keeping the names), the Copilot scaffolding lines `PART x of N`, `continue`, `continue from the last turn you gave`, `END OF TRANSCRIPT`, and everything above the first turn line. Nothing inside a turn is changed, joined or split.
2. Counts **turns** (lines matching a pattern) and **speakers** (distinct names, case-insensitive; the `Speakers:` block wins for spelling). No turn at all → a tool error, so the file stays and nothing is appended.
3. Links each speaker to the note's `attendee_links` / `organizer_link` whose target name equals the speaker name, case-insensitive. Unmatched names stay plain text (`Priya`); no person note is ever created from a transcript. A speaker written as `Tom L.` or just `Jane` is not matched — say so in the report.
4. Appends to the meeting note, under its own `## Update <ISO>`:

   ```markdown
   Transcript added via /administrator:notes.

   ### Transcript

   **Speakers:** [[Wiki/People/Jane Doe]], [[Wiki/People/Tom Lee]], Hux Waitt, Priya

   > [!note]- Transcript (9 turns, 4 speakers)
   > [13:02] Jane Doe: …
   > [13:03] Hux Waitt: …
   ```

   Over 400 cleaned lines the callout is replaced by one line `Full text: [[Administrator/Attachments/<folder>/transcript|transcript.md]] (N turns, M speakers, L lines)`, and the file is the record.

Result: `{path, turns, speakers[], speaker_links[], lines, appended_lines, linked, update_heading}`. `linked: true` = file link instead of callout. The model never re-emits the transcript: decisions, action items and waiting items go into a second, separate `vault_write(..., mode="append")` (SKILL.md step 3), and the file under `Attachments/` is never edited afterwards.

The file lives under `Administrator/`, so the "never write outside `<vault>/Administrator/`" rule holds; `vault_status.under_user_profile` does not matter for it (only Outlook exports are sandboxed). `<vault>` is `vault` from `vault_status`; one folder per meeting note, same name as the note minus `.md` — the same rule email exports use.

## 3. Report lines

Add to the usual report: "transcript: N turns, M speakers (linked: …; not an attendee: …), stored in the note / linked as `Attachments/…/transcript.md`", the decision count, and "`## Notes` left for you" or "summary written". A worked example is in `references/examples.md`.
