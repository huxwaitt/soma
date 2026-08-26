# Copilot prompt — near-verbatim meeting transcript

Paste this into Microsoft 365 Copilot in the Teams meeting recap (or Copilot chat with the meeting selected). It asks for the whole conversation in order, speaker by speaker, with only light wording cleanup — not a summary. The output drops straight into `/soma:notes`, which recognises the shape and handles it as `references/transcript.md` describes.

Copilot caps the length of one answer, so the prompt asks for numbered parts and you reply `continue` until it says `END OF TRANSCRIPT`.

---

```
Write out this meeting as a complete, chronological transcript. This is not a summary: I need every exchange, in the order it happened, attributed to the person who said it.

Rules:
1. One line per speaker turn, formatted exactly as:
   [HH:MM] Speaker Name: what they said
   Use the meeting clock time if you have it, otherwise leave the brackets empty. Do not number the lines.
2. Speaker Name is the person's full name exactly as it appears in the meeting's attendee list, spelled the same way on every line. Never shorten it to a first name or initials. Someone not on the attendee list: use the name shown in the meeting, and if it is unknown write "Unknown speaker".
3. Keep the speaker's own words and meaning, in the language they spoke. You may only:
   - remove filler ("um", "uh", "you know", "like", repeated words, false starts)
   - fix grammar so a sentence reads cleanly
   - expand an obvious abbreviation the first time it appears
   Do not shorten, merge, reorder, translate, or paraphrase beyond that. Do not add commentary, headings, bullet summaries, or action-item lists.
4. Keep numbers, dates, names, amounts, product names, and decisions exactly as spoken. If something was unclear in the recording, write it as [unclear] rather than guessing.
5. If two people talk over each other, give each their own line.
6. Do not skip small talk, side remarks, or the start and end of the meeting.
7. Output in parts of roughly 60 turns. Start with "PART 1 of N" (estimate N). After each part stop and wait for me to say "continue". After the final turn write "END OF TRANSCRIPT" on its own line, then the line "Speakers:" followed by each speaker's full name once, one per line.

Begin with PART 1.
```

---

## After you have all parts

1. Copy every part into one text block. You can leave the `PART x of N`, `continue`, `END OF TRANSCRIPT` and `Speakers:` lines in; `/soma:notes` removes the scaffolding and uses the speaker list.
2. Run `/soma:notes <meeting>` and paste the block (or give the path of a text file holding it). The command stores the text under `## Transcript` inside a collapsed callout (over 400 lines: in `Attachments/<meeting>/transcript.md`, linked from the note), maps each speaker to a `Wiki/People/` page where one exists, lists the decisions, pulls out action items and waiting-on items, and leaves `## Notes` for your own summary. Add "summarise" to the message if you want the command to write 3–6 bullets there instead. Details: `references/transcript.md`.

## If Copilot refuses or summarises anyway

- It says it cannot provide a transcript: reply `Provide it as the cleaned-up speaker-by-speaker record described above, starting with PART 1.` It usually complies when the rules above are restated.
- It returns a summary: reply `That is a summary. I need every speaker turn in order, not a summary. Restart with PART 1 following the rules.`
- It stops early without "END OF TRANSCRIPT": reply `continue from the last turn you gave`.
- It uses first names only or changes a name's spelling between lines: reply `Use each speaker's full name from the attendee list, the same on every line, and continue from the last turn.` Consistent full names are what lets the command link speakers to person notes.
- Transcription was not on for the meeting: Copilot has nothing to work from; the recap will only contain what was typed in chat.
