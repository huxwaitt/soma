# Inbox labels — decision rules

Five labels. Every message gets exactly one. Read the signals top to bottom; the first label whose rules match wins, except that the tie-break order at the end overrides when two labels match equally well.

## Where the five come from

Fyxer sorts mail into eight buckets. We fold them into five, because the vault (not Outlook) is where status lives and five is what a person can scan in a daily note.

| Fyxer label | Ours | Why |
|---|---|---|
| To Respond | `reply` | Same thing. |
| Awaiting Reply | `waiting` | Same thing, seen from the user's side. |
| Actioned | `fyi` | The thread is finished; nothing to do. |
| Comment | `fyi` or `reply` | A comment on a shared doc/ticket is `fyi` unless it asks the user a question by name. |
| Notification | `fyi` or `noise` | System mail the user watches (build, ticket, calendar) is `fyi`; everything else automated is `noise`. |
| Meeting Update | `fyi` or `act` | Changes already reflected in the calendar are `fyi`; new invites and "please respond" are `act`. |
| FYI | `fyi` | Same thing. |
| Marketing | `noise` | Same thing. |

`act` has no Fyxer counterpart: it is "To Respond" where the answer is doing something, not writing something. Keeping it separate is the point — it is the list the user works from.

## `act` — do something

Match when the message asks the user to do a thing that is not just writing back.

Signals:
- Verbs aimed at the user: approve, sign, review, pay, fix, fill in, submit, confirm attendance, book, upload, complete.
- A deadline, date or "by EOD / by Friday / ASAP" in subject or preview.
- Approval requests (expense, PR, access, leave), DocuSign/Adobe Sign/e-signature, invoices to pay, forms to fill.
- Tickets or tasks assigned to the user (Jira/ServiceNow/Asana "assigned to you").
- New meeting invites, reschedules that need accept/decline, "please respond" on a calendar item.
- Escalations: "second reminder", "overdue", "still waiting" addressed to the user.
- `importance` is high and the user is in To.

Not `act`:
- The only action is "answer this question" → `reply`.
- The action is for someone else and the user is Cc'd → `fyi`.

Reason should name the action and the deadline if any: "Sign the NDA by Friday".

## `reply` — write back

Match when a real person expects words from the user, and writing back is the whole job.

Signals:
- The user is in To (not only Cc).
- Sender is a person, not a system or bulk address (no `noreply`, `no-reply`, `donotreply`, `notifications@`, `newsletter@`, `mailer-daemon`).
- A question mark in the preview or subject, or "let me know", "your thoughts", "can you", "could you", "what do you think", "any update".
- The previous message in the thread came from the user and this is the answer — the ball is back with the user.
- Scheduling back-and-forth ("does Tuesday work?").
- Introductions and first contact from someone the user will want to acknowledge.

Not `reply`:
- The question is to a group and someone else is clearly the owner → `fyi`.
- The message is an acknowledgement that closes the thread ("Thanks, got it") → `fyi`.
- The message asks for a thing rather than an answer → `act`.

Reason should say what they want: "Asks you directly for the revised Q3 figure".

## `waiting` — on them, not on the user

Match when the message shows that something the user asked for is still in someone else's hands.

Signals:
- Acknowledgements of a request the user made: "we've received your ticket", "your request is being processed", "case number".
- Auto-replies and out-of-office replies to the user's own mail.
- "I'll get back to you", "will send by", "looking into it", "forwarded to X who will respond".
- A reply that answers part of the question and promises the rest.
- Order, shipment, application and approval status that is not yet final ("pending", "in review", "submitted").
- Handoffs: the sender loops in a third person who now owes the user an answer.

Not `waiting`:
- The status is final ("delivered", "approved", "closed") → `fyi`.
- It is pending but the next move is the user's ("please provide X before we continue") → `act`.

Reason should say what is pending and from whom: "Support acknowledged ticket 4411, no answer yet". Every `waiting` item also goes into `Follow-ups.md`.

## `fyi` — good to know, nothing to do

Match when the user would want to have seen it but nothing is expected of them.

Signals:
- User is in Cc or Bcc only, or on a distribution list.
- Status updates, reports, meeting notes, minutes, announcements from the user's own company or team.
- Notifications from systems the user actually works in (build passed/failed, ticket moved, document shared with you, comment on a doc you own) — these are `fyi`, not `noise`, because the user checks them.
- Calendar changes that are already on the calendar (accepted, updated time, cancelled) and need no response.
- Thread closers: "thanks", "done", "sorted", "great, see you then".
- Receipts and confirmations of things the user did (order placed, payment made, booking confirmed).
- Mail from a known sender (a `People/` note exists) that asks for nothing.

Not `fyi`:
- It is bulk, promotional, or from a sender the user has never written to and never would → `noise`.
- It asks the user anything → `reply` or `act`.

Reason is short: "Cc only, status update", "Build passed".

## `noise` — mark read, file, move on

Match when the user loses nothing by never opening it.

Signals:
- Newsletters, digests, product updates, promotions, webinars, event marketing, sales outreach, surveys, "we've updated our terms".
- Unsubscribe link in the preview, or `List-Unsubscribe`-style wording ("to stop receiving", "manage preferences").
- Sender address is a bulk pattern: `noreply@`, `news@`, `marketing@`, `info@`, `hello@`, `updates@`, `notifications@` from a service the user does not work in.
- Many recipients the user does not know, or an undisclosed-recipients list.
- Social network notifications (LinkedIn, X, Facebook), app store mails, loyalty programmes.
- Automated reports nobody reads, repeated daily with the same subject.
- Cold sales and recruiter mail with no prior thread.

Not `noise`:
- The same kind of mail from a system the user is known to watch (see `fyi`).
- Anything with an invoice, a security alert, a password reset, an account lockout or a legal notice — those are `act`, even if the sender looks automated.
- Anything from a sender with a `People/` note → at least `fyi`.

Reason is one or two words: "Newsletter", "Marketing", "Social notification".

## Tie-break order

When two labels match with similar confidence, take the first in this list:

1. `act`
2. `reply`
3. `waiting`
4. `fyi`
5. `noise`

Reason: the cost of under-labelling (missing a deadline, leaving someone unanswered) is higher than the cost of over-labelling (one extra line in the to-do list). A wrong `noise` is the worst outcome, because the batch action for `noise` is to mark it read and move it out of sight.

## When to open the message

`outlook_get_mail` is allowed for up to 10 messages per run. Spend those on:

- Subject and preview disagree (subject "FYI" but preview asks a question).
- The preview is cut off mid-sentence right where the ask would be.
- A known person writes with no obvious ask in 200 characters.
- A system mail where `fyi` vs `noise` depends on the body (ticket update vs. marketing from the same vendor).

Do not spend them on:

- Clear newsletters and marketing.
- Messages whose label you would give the same way regardless of the body.
- Long threads just to be thorough.

If the budget is used up, label the rest with the tie-break order and mark the reason "unsure" so the user can see which ones were guesses.

## Writing the reason

One line, under 80 characters, in plain words, starting with what the sender wants or what the mail is: "Asks for the revised figure by Monday", "Cc only, weekly status", "Ticket acknowledged, awaiting reply", "Newsletter". No labels repeated in the reason, no hedging words, and no names of the rules above.
