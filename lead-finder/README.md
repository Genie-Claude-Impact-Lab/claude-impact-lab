# Lead Finder

**Find small businesses to sell to, with a real email and a reason to contact them first.**

Answer six questions. Lead Finder searches Google Maps, opens each business’s website to find an email, reads its About page to find the owner’s name, and gives you a ranked list with a first email ready to send. No code, no spreadsheet skills.

Built at the Claude Impact Lab Hackathon, Seattle, October 2026.

## Use it

**Open the app:** [Lead Finder](PASTE_STREAMLIT_LINK_HERE)

1. **Say who you sell to, in one sentence.** For example: “I sell invoice review software to small accounting firms in Seattle.” Claude fills in the details: business types, city, distance, and who you usually talk to. Check them and change anything.
2. **Press Find leads.** Watch each step as it happens: businesses found, chains set aside, websites visited, emails found, websites read by Claude. It takes 30 to 60 seconds.
3. **Work through your leads.**
   - **Best leads:** each card shows the owner’s name, what the business does, **why they might need you** (written by Claude from their own website), the email, and a **Write my first email** button.
   - **Map:** see where every lead is.
   - **Need an email:** real businesses with no email on their website. Call them, paste the email you get, and the lead moves up.
   - **All in a table:** sort, scan, and download as a spreadsheet.

## What makes a good lead

| We check | How |
|---|---|
| It’s a real, open business | Found on Google Maps, and Google doesn’t list it as closed |
| It’s active | Its newest Google review is recent |
| There’s a valid email | Found on the business’s own website, then verified: correct format, not a throwaway address, the domain receives mail, and (where the mail server allows) the mailbox exists. Addresses that fail are left out |
| You know who to ask for | The owner’s name, read from their About page |
| It’s your kind of customer | The type and area you picked; chains and your do-not-contact list are skipped |
| They’re likely to need you | Claude reads their website and rates the fit from 0 to 100, with a one-line reason |

Points out of 100: personal company email 30 (shared inbox 15, free account 10), confirmed mailbox 5, owner’s name 20 (any name 10), Google review in the last 3 months 20 (last year 10), website 10, phone 5, a strong fit or a sign they need you 15. **Contact now** is 70 or more, **Worth a try** is 50–69.
Businesses Claude rates as a weak fit (under 40) go to **Later**, however good their contact details.

## Built to avoid the problems of big lead tools

| Common complaint about Apollo and similar tools | What Lead Finder does |
|---|---|
| Contact data is out of date or wrong | Emails come straight from each business’s own website today, and every one is verified before you see it, with a clear label: Mailbox confirmed, Domain accepts mail, or Can’t confirm mailbox |
| AI makes things up | Claude may only use a name that is written on the business’s website. Anything else is thrown out, and you’re told |
| Weak on local small businesses | Built on Google Maps, where local businesses actually are |
| Hard to set up, too many features | Six questions and one button |
| People who opt out keep getting emailed | A do-not-contact list that’s always left out |
| Contracts and credits | Free and open source. You only pay Google for searches beyond its free monthly allowance |

---

## Set it up (about 20 minutes, no code)

You need three things: this code on GitHub, a Google Maps key, and a free Streamlit account. A Claude key is optional but recommended.

### 1. Get a Google Maps key (about 10 minutes)

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and sign in with a Google account.
2. At the top, click the project picker, then **New project**. Name it `lead-finder` and click **Create**.
3. In the search bar, type **Places API (New)**, open it, and click **Enable**. If Google asks you to set up billing, add a card. Google includes a free monthly allowance, and a demo uses very little of it.
4. In the search bar, type **Credentials**, open it, click **Create credentials → API key**, and copy the key.
5. Click the key, under **API restrictions** choose **Restrict key**, tick **Places API (New)**, and click **Save**. This stops anyone using the key for anything else.

### 2. Get a Claude key (optional, about 2 minutes)

Go to [console.anthropic.com](https://console.anthropic.com), open **API Keys**, click **Create Key**, and copy it. With it, Claude reads About pages to find owners’ names and writes personalized emails. Without it, the app uses simpler pattern matching and a template email.

### 3. Put the app online (about 5 minutes)

1. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub.
2. Click **Create app**, then **Deploy a public app from GitHub**.
3. Repository: `karleybrowning/claude-impact-lab`. Branch: `main`. Main file path: `lead-finder/app.py`.
4. Click **Advanced settings**. In **Secrets**, paste the lines below with your keys:
   ```
   GOOGLE_MAPS_API_KEY = "your-google-key"
   ANTHROPIC_API_KEY = "your-claude-key"
   ```
5. Click **Deploy**. After a minute or two you get a link. Put it at the top of this README.

**Never put keys in GitHub.** They go only in Streamlit’s Secrets box.

### Free mode (no Google key)

Without a Google key the app runs in free mode using OpenStreetMap, a free public map. It works, but expect less:
in a test of accounting firms within 10 miles of Seattle it found 76 offices, of which 22 were chains and only 14 listed
a website. Several of those websites had since been put up for sale, which usually means the business closed or moved.
Lead Finder spots these and skips them, but you’ll end up with a handful of good leads rather than dozens.
The free map servers can also be slow (30 seconds or more) or busy; the app retries other servers automatically,
and repeating the same search within an hour is instant. Add a Google key when you want fuller results.

---

## For developers

`finder.py` does the work (search, website visits, email checks, Claude, scoring); `app.py` is the Streamlit page.

```bash
pip install -r requirements-dev.txt
pytest                      # 42 tests, all offline, using fake Google results, fake websites and a fake Claude
streamlit run app.py        # set GOOGLE_MAPS_API_KEY and ANTHROPIC_API_KEY first
```

The tests cover finding emails in real-looking HTML (including Cloudflare-protected emails), picking the best email, skipping closed businesses, chains and far-away places, dropping emails whose domain can’t receive mail, rejecting names Claude made up, skipping businesses whose website is up for sale, retrying busy free map servers, the do-not-contact list, a broken website not stopping the run, plain-English error messages, and clicking through the page itself.

## Data and privacy

Lead Finder only reads public pages: Google Maps listings and each business’s own website. It never sends anything to the businesses. You review and send every email yourself. US law (CAN-SPAM) requires that you say who you are, include your business address, and offer a way to opt out: every draft includes these.

## License

MIT

### About email verification

Lead Finder checks every email in layers and never sends anything. The last layer asks the business’s mail server whether the mailbox exists. Some hosting services, possibly including Streamlit Cloud, block the connection this needs. When that happens the app says so and labels emails **Domain accepts mail** instead of **Mailbox confirmed**. For full mailbox checks at scale, a paid verification service (such as ZeroBounce or NeverBounce) can be added later.
