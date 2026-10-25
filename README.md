# Lead Ranker

**Know which leads to contact first.**

You’ve found a list of businesses that might buy from you. Lead Ranker tells you who to contact first, why, and writes the first email for you. No setup, no code, no spreadsheet skills needed.

Built at the Claude Impact Lab Hackathon, Seattle, October 2026.

## Use it in 3 steps

**Open the app:** [Lead Ranker](PASTE_ARTIFACT_LINK_HERE)

**1. Describe your best customers in your own words.**
What you sell, who buys it, where they are, how big they are, and who you usually talk to.

![Step 1](docs/step1.png)

**2. Paste the businesses you’ve found.**
Anything works: text copied from Google Maps, a spreadsheet, or your own notes.

![Step 2](docs/step2.png)

**3. Press “Rank my leads.”**
Every business gets a priority: **Contact now**, **Worth a try**, **Later**, or **Skip for now**, with the reasons in plain words. For your best leads, press **Write my first email**, fill in the parts in [brackets], copy it, and send it from your own email.

![Step 3](docs/step3.png)

Not sure what to paste? Press **Try an example** in the app, or see the [examples folder](examples/).

## How the ranking works

A business is skipped if it’s listed as closed or has no email yet. Everyone else gets points out of 100: **Contact now** is 70 or more, **Worth a try** is 50–69, **Later** is below 50.

| What we look at | Points |
|---|---|
| A personal email at their company | 30 |
| A shared inbox (info@…) or a free account (Gmail…) | 15 or 10 |
| You know the owner or manager’s name, or just someone’s name | 20 or 10 |
| Customers reviewed them in the last 3 months, or the last year | 20 or 10 |
| The kind of business you serve | 15 |
| In your area and the right size | 15 |

Simple rules (email type, how recent the reviews are, closed or not) are checked by the app itself, so results are consistent. Judgment calls (is this your kind of customer, are they in your area, is this person the decision maker) are made by Claude.

## Your data

Your description and list are sent to Claude only when you press **Rank my leads** or **Write my first email**. The app never contacts any business. You review and send every email yourself.

When you email people you don’t know, US law (CAN-SPAM) requires that you say who you are, include your business address, and let them opt out. The drafted emails include placeholders and an opt-out line for this.

---

## For developers

**Web app:** `index.html` is a single self-contained file. When opened on claude.ai it uses Claude to read messy lists and draft emails. Opened anywhere else, it falls back to simple word matching and needs a spreadsheet with a header row (see `examples/sample_leads.csv`).

**Python version:** `python/` scores a CSV from the command line and can also check whether an email’s domain can receive mail.

```bash
cd python
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your_key_here
python score_leads.py leads.csv intake.json          # with Claude
python score_leads.py leads.csv intake.json --no-llm # without Claude
```

## Team

| Name | Role |
|---|---|
| | Lead qualification and scoring |
| | Lead discovery (finding businesses and emails) |
| | |

## License

MIT
