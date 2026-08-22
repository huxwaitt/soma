# Copilot prompt — near-verbatim meeting transcript

Paste this into Microsoft 365 Copilot in the Teams meeting recap (or Copilot chat with the meeting selected). It asks for the whole conversation in order, speaker by speaker, with only light wording cleanup — not a summary. The output drops straight into `/administrator:notes`.

Copilot caps the length of one answer, so the prompt asks for numbered parts and you reply `continue` until it says `END OF TRANSCRIPT`.

---

```
Write out this meeting as a complete, chronological transcript. This is not a summary: I need every exchange, in the order it happened, attributed to the person who said it.

Rules:
1. One line per speaker turn, formatted exactly as:
   [HH:MM] Speaker Name: what they said
   Use the meeting clock time if you have it, otherwise leave the brackets empty.
2. Keep the speaker's own words and meaning. You may only:
   - remove filler ("um", "uh", "you know", "like", repeated words, false starts)
   - fix grammar so a sentence reads cleanly
   - expand an obvious abbreviation the first time it appears
   Do not shorten, merge, reorder, or paraphrase beyond that. Do not add commentary, headings, bullet summaries, or action-item lists.
3. Keep numbers, dates, names, amounts, product names, and decisions exactly as spoken. If something was unclear in the recording, write it as [unclear] rather than guessing.
4. If two people talk over each other, give each their own line.
5. Do not skip small talk, side remarks, or the start and end of the meeting.
6. Output in parts of roughly 60 turns. Start with "PART 1 of N" (estimate N). After each part stop and wait for me to say "continue". After the final turn write "END OF TRANSCRIPT" on its own line, followed by a list "Speakers:" with each name once.

Begin with PART 1.
```

---

## After you have all parts

1. Copy every part into one text block (remove the "PART x of N" and "continue" lines).
2. Run `/administrator:notes <meeting> ` and paste the block. The `notes` command stores it under `## Transcript` inside a collapsed callout, maps each speaker to a `People/` note where one exists, and leaves `## Notes` for your own summary.

## If Copilot refuses or summarises anyway

- It says it cannot provide a transcript: reply `Provide it as the cleaned-up speaker-by-speaker record described above, starting with PART 1.` It usually complies when the rules above are restated.
- It returns a summary: reply `That is a summary. I need every speaker turn in order, not a summary. Restart with PART 1 following the rules.`
- It stops early without "END OF TRANSCRIPT": reply `continue from the last turn you gave`.
- Transcription was not on for the meeting: Copilot has nothing to work from; the recap will only contain what was typed in chat.
