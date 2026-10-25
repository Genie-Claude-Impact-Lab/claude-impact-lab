# Team Notes (for us, not part of the product)

## Team
BizAutoGenie (Workflow-Genie.com): Manohar Karamballi (lead), Aashi Juneja, Justin Long, Karley Browning. Shashank Katkar appears in the shared notes. Challenge and judging criteria are not on the team page; check hack.claudeseattle.org/resources.

## Competitor research
Clay and Apollo are paid and hard for non-technical users. Complaints we heard: data errors, hard to get started (connecting accounts/email), and AI sequences that created more work. Our pitch: simple, quality-first, actionable.

## Timeline (from the transcript)
- Submission 5:30 PM; code freeze around 4:00 PM.
- About 1 hour for debugging, plus the demo video.
- Order: repo and keys, search and enrichment, scoring, UI, quality check, pitch.

## Quality proof for the demo
- Coverage: of N businesses found, % passing filters and % with a personal email.
- Precision: hand-check 20 A-tier leads.
- Tune weights from the check.

## Open team decisions
- Frontend: Streamlit (fast) vs custom mobile-first web app.
- API budget (Google Places billing, Hunter.io).
- Demo customer: Manohar's automation product?
- Who owns what; agree on one repo layout first.

## Risks
- Google Places billing/key setup: do first.
- CAN-SPAM (opt-out and physical address in commercial email): mention in the pitch.
- Keys go in `.env`, never committed; confirm `.gitignore` covers it.
