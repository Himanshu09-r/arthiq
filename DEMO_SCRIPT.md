# Arthiq demo script (about 6 minutes)

## Before you go on stage
1. Stop uvicorn. Run `python demo_reset.py`, then `uvicorn app.api.main:app --reload`.
2. Open 4 tabs: `/` (voice app), `/insights`, `/console`, `/dashboard`.
3. Check the console clock is between 09:00 and 20:00 (quiet hours). If not, press "+6 hours" until it is.
4. Use headphones or a quiet corner. Test the mic once. Pick Hindi.
5. Open the backup video in another window.

## 1. Voice entry (Hindi) - 1.5 min  [tab: /]
- Say: "Ramesh ne do kilo chawal aur ek biscuit ka packet udhar liya"
- Arthiq asks "which Ramesh?" -> say "Kumar".
- Read-back (Rs 130) -> say "haan". Show ledger and stock tables updating.
- Say: "Sharma ji ne 600 ka udhar liya" -> haan. Then: "Sharma ji ne 600 nahi, 300 diye" -> read-back says 300 -> haan.
  Point out: correction handled, price/total/balance come from code, not the LLM.
- Press Language -> Marathi. Say: "सुनीता देशमुख ने दोन किलो तांदूळ उधार घेतले". Read-back says तांदूळ.

## 2. Stock and cash - 1.5 min  [tab: /insights]  (do this BEFORE fast-forwarding)
- Alerts: rice, sugar, atta low; biscuit near expiry; chai patti dead stock. Press Speak alerts.
- Cash Guardian: Rs 8,000 cash vs about Rs 6,756 needed. Press Explain by voice.
  Say: "dues are not cash until paid".
- Set cash to 4000, Save: rice is skipped, the what-if names who to chase.
- Draft order -> on /dashboard press the mic and say "haan" (or Approve). Nothing is sent without approval.
- /dashboard Briefing tab: Generate, Play.

## 3. Autonomous collection - 2 min  [tab: /console]
- Click "+15 days" (then "+6 hours" if the clock is in quiet hours), then "Run scheduler now".
- Outbox shows the Hindi reminder with a pay link. Open the link -> Pay now.
  Voice alert plays, khata closes. Press "send same webhook again": ignored (idempotent).
- Pick another customer, click the chip "Friday ko dunga", Send. Promise appears (Arthiq Memory).
  Click "+7 days", "Run scheduler now": promise turns OVERDUE and the ladder resumes.
- Pick a third customer, send "Ye galat hai, maine nahi liya": messaging stops, balance unchanged.

## 4. Trust - 1 min  [tab: /dashboard]
- Inbox: dispute card -> Resolve. Escalation card (use +21 days earlier if you want it) -> Pause / Freeze.
- Audit log tab: search "block" or "inbox_action". Append-only, every rule decision is visible.

## If something breaks
| Problem | Do this |
|---|---|
| Mic does not work | Use the text box on `/` (POST /text/turn); everything else is identical |
| Sarvam / internet down | Show the backup video, then the audit log and dashboard (they need no network) |
| No voice alert | Text of every alert is on screen; keep going |
| Outbox empty after Run scheduler | Quiet hours: press "+6 hours", run again |
| "database is locked" | Click the button again |
| Everything is messy | Ctrl+C, `python demo_reset.py`, restart |

## Slides: say "planned", not "built"
Real Paytm links and webhook signature check, real WhatsApp/SMS/calls, Celery + Redis (we use APScheduler),
PostgreSQL (we use SQLite), Arthiq Proof, Arthiq Negotiator, stock-in by voice, voice balance queries,
cash correction by voice, multi-shop login, native-speaker review of bn/ta/te/kn/ml/pa/od templates
(collection, cash and briefing templates exist for hi/en/mr/gu only).