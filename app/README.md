# Leadline

**Find local businesses to sell to, with a real email, a reason to reach out, and a first email that sounds like you.**

Describe who you sell to. Leadline searches Google Maps (or a free map), visits each business's website to find and check an email, reads it for the owner's name and how well they fit, ranks who to contact first, and puts everything on a pipeline board where you can write, edit and send each email from your own email app.

Built at the Claude Impact Lab Hackathon, Seattle, October 2026. Open source (MIT).

## Run it on your computer

You need **Python 3.10 or newer**. Check with `python3 --version`. If it's older (Macs ship with 3.9), install a newer one from [python.org/downloads](https://www.python.org/downloads/) or, on a Mac with Homebrew, run `brew install python@3.12`.

1. Get the code and open the app folder:

   ```bash
   git clone https://github.com/Leadline-Claude-Impact-Lab/claude-impact-lab.git
   cd claude-impact-lab/app
   ```

2. Set it up once (creates a private Python environment and installs what the app needs):

   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -r requirements-dev.txt
   ```

   On Windows use `.venv\Scripts\pip` instead of `.venv/bin/pip`, and `.venv\Scripts\python` instead of `.venv/bin/python` below.

3. Add your keys (optional, but the app is much better with them):

   ```bash
   cp .env.example .env
   ```

   Open `.env` in any text editor and paste each key after its `=` sign. `.env` stays on your computer and is never uploaded to GitHub.

4. Check your keys (takes a few seconds, and tells you in plain words what to fix):

   ```bash
   .venv/bin/python check_keys.py
   ```

5. Start it:

   ```bash
   .venv/bin/python run.py
   ```

   Your browser opens at http://localhost:8000. Press Ctrl+C in the terminal to stop it.

## Keys

| Key | What it does | Without it |
|---|---|---|
| `TOMTOM_API_KEY` | Finds businesses on TomTom's map: name, address, website, phone, and whether it's a chain. Free, no credit card, 2,500 searches a month. TomTom has no review data, so ranking leans on emails, owner names, websites and phone numbers | Free mode uses OpenStreetMap: fewer businesses, and the free servers are sometimes busy |
| `GOOGLE_MAPS_API_KEY` | Finds businesses on Google Maps, with reviews and open or closed status | Free mode uses OpenStreetMap: fewer businesses, no reviews, and the free servers are sometimes busy |
| `ANTHROPIC_API_KEY` | Claude turns your one-sentence description into a search, reads websites for owners' names and fit, and writes emails | Fill in the questions yourself; emails use a plain template |

**TomTom key:** sign up at [developer.tomtom.com](https://developer.tomtom.com) (no credit card), open the dashboard, create an API key, and paste it into `.env` after `TOMTOM_API_KEY=`. When the free 2,500 monthly searches are used up TomTom blocks further requests instead of charging you. One Leadline search uses 1 to 5 of them, depending on how many kinds of business you pick.

**Which map is used:** Google if a Google key is set, otherwise TomTom if a TomTom key is set, otherwise OpenStreetMap. To force one, set `MAP_SOURCE=tomtom` (or `google`, or `osm`) in `.env`.

**Google key:** in [Google Cloud Console](https://console.cloud.google.com), create a project, enable **Places API (New)**, then **Credentials → Create credentials → API key**. Restrict the key to Places API (New) and set a budget alert.

**Claude key:** in the [Claude console](https://platform.claude.com), open **API keys → Create key**.

**Never put a key in the code, a chat, a doc or GitHub.** Anyone who sees it can run up charges.

## How it works

1. **Tell us who you sell to.** One sentence (Claude fills in the details) or the guided questions: kinds of businesses, city, distance, who you usually talk to, and more options.
2. **Find leads.** About 30 to 60 seconds. You see each step as it happens.
3. **Work your pipeline.** Leads with an email land on the board, best first, with a tier (Contact now, Worth a try, Later), the next step and the reasons. Open one to see the facts, the email check, the pages we read, and a draft email in three styles. **Write with Claude** drafts one from what we found, and **Edit** lets you change it or ask for a rewrite. **Send from email app** opens your own email; Leadline never sends anything itself.
4. **Need an email** lists real businesses with no email on their website. Call them, paste the email you get, and we check it and move them onto the board.
5. **Your business profile** is set up once: what you sell, the problem you solve, your ideal and best customers, who you talk to, a result you're proud of, your offer and your address (the law requires it in sales emails). Add documents (PDF, Word, saved emails, text) to give it more context: documents become background for your emails, past emails set their voice, and with a Claude key we read them to fill in empty questions. You can keep several businesses and switch between them; **Settings** shows which keys are connected.

Your searches, drafts and profile are saved in your browser.

### What makes a good lead

Points out of 100: personal email at their company 30 (shared inbox 15, free account 10), mailbox confirmed 5, owner or decision-maker named 20 (any name 10), Google review in the last 3 months 20 (last year 10), website 10, phone 5, a sign they need you 15, strong fit according to Claude 15. **Contact now** is 70 or more, **Worth a try** 50 to 69. Weak fits go to Later. Closed businesses, chains (if you choose), parked websites, places outside your area and your do-not-contact list are set aside with the reason.

### Emails that don't sound like AI

Drafts use only facts we verified about the business, never invent details, stay under about 110 words, avoid AI-sounding words and spam phrases, and get one automatic rewrite if a check finds problems. Every email ends with your name, business, address and an opt-out line, as US law (CAN-SPAM) requires. Anything we couldn't fix shows as **Check before you send**.

## For developers

| File | What it does |
|---|---|
| `finder.py` | Search, website visits, email checks, Claude reading, scoring (from the Lead Finder prototype) |
| `emails.py` | Email drafting with the human-sounding checks |
| `server.py` | Web server and API |
| `static/index.html` | The website (from the Leadline dashboard) |
| `run.py` | Starts the server and opens the browser |

```bash
.venv/bin/python -m pytest -q    # 82 tests, all offline
```

Settings in `.env`: `CLAUDE_MODEL` (default `claude-sonnet-5-5`) and `SEARCHES_PER_HOUR` (per visitor, default 20).

Mailbox checks talk to each business's mail server on port 25. Many home networks and hosting services block that; the app detects it and labels emails **Domain accepts mail** instead of **Mailbox confirmed**.

## Data and privacy

Leadline reads only public pages: map listings and each business's own website. It never contacts a business. Text from websites goes to Claude as information to work from; Claude is told to treat it as data, but read every draft before you send it.
