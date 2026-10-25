# BizAutoGenie: Product Plan (DRAFT)

What the small business owner gets. Team logistics, competitor research and hackathon notes live in [TEAM_NOTES.md](TEAM_NOTES.md).

## 1. One-line pitch

Describe what you sell. The tool finds real local businesses that fit, gives you verified contact emails, ranks them, and tells you who to contact first and why.

## 2. Who it's for

Small and mid-size business owners. Not technical, often away from a laptop, so a **good mobile experience is required**. Setup must be a couple of clicks, with no DNS or API configuration on their side. Email is the main channel, not phone.

## 3. Principles

1. Several businesses can use it, each with their own settings.
2. Easy for non-technical people.
3. Extensible: new lead sources and new content context can be plugged in later.
4. Easy to install.
5. Reporting, starting with how many contacts were sent.
6. Lead quality matters more than lead count.

## 4. MVP

### 4.1 Tell us who you're looking for (two ways, same result)
- **Guided questions:** what you sell, ZIP, optional business category, how many leads.
- **Describe it in your own words:** a single text box (typed or dictated). The tool builds an ideal-customer profile from it and asks follow-up questions for anything missing.
- Optional: suggested categories (e.g. "we automate reconciliation" suggests accounting firms, bookkeepers, property managers).

### 4.2 Find businesses
Search by ZIP and category for local businesses with name, address, website, phone, rating, review count and open/closed status.

### 4.3 Find contacts
- Look for emails on each business's homepage and contact/about/team pages.
- Label each as a named person's email or a generic one (info@, hello@).
- Check that the email's domain can actually receive mail.
- Never present guessed addresses as verified; if added later, label them "unverified".

### 4.4 Score and rank
Drop a lead if the business is closed, the website is down, or there is no usable email.

| Signal | Points |
|---|---|
| Personal email found | 40 |
| Generic email only | 20 |
| Review within 90 days (P2) | 20 |
| Review within 12 months (P2) | 10 |
| 10+ total reviews | 10 |
| Category exact match | 10 |
| Email domain matches website | 10 |
| Phone present | 5 |

Tier A = 70+, Tier B = 40-69, below 40 is dropped. Possible extra factors: contact name and role (owner, founder, manager), and location/size fit.

### 4.5 What the owner sees
- **Swipe-card view:** one lead per card, swipe yes or no. Tap a card to reveal tabs (contact, reviews, why it ranked).
- **A recommended action, not just a score:** "Contact Jane first. She's the owner and the shop has recent reviews."
- **View in the app and export to CSV/Excel:** browse on a phone, export from a computer.

### 4.6 Phase 2
- "Write email" button: a personalized draft per lead, editable in the app.
- Reporting on contacts sent, later response rate.
- Multi-tenant support, Docker, more lead sources.

## 5. Open product questions

1. Market: US (Seattle) or elsewhere? The notes said "pincode".
2. Is the swipe UI in the MVP or a stretch?
3. Which fields are required in the guided intake?
