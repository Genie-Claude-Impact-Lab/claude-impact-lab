# Leadline

**A pipeline dashboard for the leads you've found.**

Leadline puts your leads on a board (New, Drafted, Emailed, Replied), shows why each one is a good fit, and writes a first email for each lead from what it knows about them and about your business.

Built at the Claude Impact Lab Hackathon, Seattle, October 2026.

## Run it

Open `index.html` in a browser. It works offline apart from the font and the CSV reader, which load from a CDN.

- Two demo businesses are built in (a coffee roaster and a SaaS company). Switch between them in the sidebar.
- **Import leads** takes a CSV with at least `business_name` and `email` columns.
- **Your business** sets the company, pitch, proof and sign-off used in every email.
- Drafts, stages and your profile are saved in your browser's local storage.

When it's opened as a Claude artifact, the Ask box and the email rewrite button use Claude. Opened anywhere else, the Ask box only filters leads by keyword.

All lead data in the demo is made up.
