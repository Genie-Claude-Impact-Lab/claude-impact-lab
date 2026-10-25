"""Lead Finder: a web page small business owners can use without any setup."""
import csv
import io
import os

import streamlit as st

import finder

st.set_page_config(page_title="Lead Finder", page_icon="🎯", layout="centered")


def secret(name: str) -> str:
    try:
        v = st.secrets.get(name, "")
    except Exception:  # no secrets file
        v = ""
    return v or os.environ.get(name, "")


GOOGLE_KEY = secret("GOOGLE_MAPS_API_KEY")
CLAUDE_KEY = secret("ANTHROPIC_API_KEY")
CLAUDE_MODEL = secret("CLAUDE_MODEL") or "claude-sonnet-5-5"


@st.cache_resource
def claude_client(key: str):
    if not key:
        return None
    import anthropic
    return anthropic.Anthropic(api_key=key)


st.title("Find businesses to sell to")
st.write("Answer a few questions. We’ll search Google Maps, visit each business’s website to find an email, "
         "and tell you who to contact first, with a first email ready to send.")

if not GOOGLE_KEY:
    st.info("Running in free mode with OpenStreetMap: fewer businesses and no reviews. "
            "Add a Google Maps key for full results (see the README).")

# ---------------------------------------------------------------- guided questions
with st.form("questions"):
    sell = st.text_input("1. What do you sell?", key="sell",
                         placeholder="Example: software that speeds up invoice reviews for small firms")
    types = st.pills("2. What kinds of businesses buy from you? Pick one or more.", list(finder.TYPES),
                     selection_mode="multi", key="types")
    types_other = st.text_input("Something else? Type it here.", key="types_other",
                                placeholder="Example: dog groomers")
    c1, c2 = st.columns([3, 2])
    city = c1.text_input("3. Which city should we search around?", key="city", placeholder="Example: Seattle, WA")
    radius = c2.pills("How far?", list(finder.RADIUS_MILES), selection_mode="single", key="radius",
                      default="Within 10 miles")
    deciders = st.pills("4. Who do you usually talk to?", list(finder.DECIDER_WORDS), selection_mode="multi",
                        key="deciders", default=["The owner"])
    signals = st.pills("5. What tells you a business needs you? (optional)", finder.SIGNALS,
                       selection_mode="multi", key="signals")
    avoid = st.pills("6. Who should we skip? (optional)", ["Chains and franchises"], selection_mode="multi",
                     key="avoid", default=["Chains and franchises"])
    how_many = st.select_slider("7. How many businesses should we look at?", [20, 40, 60], value=40, key="how_many",
                                help="More takes longer: about a minute for 40.")
    with st.expander("Businesses you never want to contact (optional)"):
        dnc = st.text_area("One business name per line. We’ll always leave these out.", key="dnc")
    go = st.form_submit_button("Find leads", type="primary", use_container_width=True)

if go:
    profile = {"sell": sell.strip(), "types": types or [], "types_other": types_other.strip(), "city": city.strip(),
               "radius": radius or "Within 10 miles", "deciders": deciders or ["The owner"], "signals": signals or [],
               "avoid": avoid or [], "do_not_contact": (dnc or "").splitlines()}
    if not profile["sell"]:
        st.error("Tell us what you sell (question 1). We use it to write your emails.")
    elif not profile["types"] and not profile["types_other"]:
        st.error("Pick at least one kind of business (question 2), or type one in.")
    elif not profile["city"]:
        st.error("Tell us which city to search around (question 3).")
    else:
        bar = st.progress(0.0, text="Starting…")
        try:
            result = finder.find_leads(profile, limit=how_many, google_key=GOOGLE_KEY,
                                       claude_client=claude_client(CLAUDE_KEY), claude_model=CLAUDE_MODEL,
                                       progress=lambda m, f: bar.progress(min(1.0, f), text=m))
            st.session_state["result"], st.session_state["profile"] = result, profile
            st.session_state.pop("drafts", None)
        except finder.SearchError as e:
            st.error(str(e))
        bar.empty()

# ---------------------------------------------------------------- results
result = st.session_state.get("result")
if result:
    leads, profile = result["leads"], st.session_state["profile"]
    st.header("Your leads")
    counts = {t: sum(l["tier"] == t for l in leads) for t in finder.TIER_LABEL}
    cols = st.columns(5)
    for col, t in zip(cols, finder.TIER_LABEL):
        col.metric(finder.TIER_LABEL[t], counts[t])
    st.caption(f"Found on {result['source']}. Emails come from each business’s own website. "
               + ("Owners’ names were read from their About pages by Claude." if CLAUDE_KEY else ""))

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=finder.CSV_COLUMNS)
    w.writeheader()
    w.writerows(finder.to_rows(leads))
    st.download_button("Download as a spreadsheet", buf.getvalue(), "leads.csv", "text/csv")

    drafts = st.session_state.setdefault("drafts", {})
    tabs = st.tabs([f"{finder.TIER_LABEL[t]} ({counts[t]})" for t in finder.TIER_LABEL])
    for tab, t in zip(tabs, finder.TIER_LABEL):
        with tab:
            group = [l for l in leads if l["tier"] == t]
            if not group:
                st.write("Nothing here.")
            for i, l in enumerate(group):
                with st.container(border=True):
                    st.subheader(l["business_name"])
                    meta = [x for x in [
                        l.get("contact_name") and (l["contact_name"] + (", " + l["contact_title"] if l.get("contact_title") else "")),
                        l.get("email"), l.get("phone"), l.get("address")] if x]
                    st.caption("  |  ".join(meta))
                    st.markdown(f"**{l['next']}**")
                    if l["check"]:
                        st.warning("**Check before you send**\n\n" + "\n".join(f"- {c}" for c in l["check"]))
                    if l["improve"] and t != "now":
                        st.info("**To make this lead better**\n\n" + "\n".join(f"- {c}" for c in l["improve"]))
                    if l["why"]:
                        st.markdown("\n".join(f"- {x}" for x in l["why"]))
                    links = [f"[Website]({l['website']})" if l.get("website") else "",
                             f"[{l['found_on']}]({l['maps_url']})" if l.get("maps_url") else ""]
                    st.markdown("  ".join(x for x in links if x))
                    if t in ("now", "try") and l.get("email"):
                        key = f"draft-{l['id']}"
                        if st.button("Write my first email", key=f"btn-{l['id']}-{t}-{i}"):
                            mail = None
                            try:
                                mail = finder.claude_email(claude_client(CLAUDE_KEY), CLAUDE_MODEL, profile, l)
                            except Exception:
                                mail = None
                            drafts[key] = mail or finder.template_email(profile, l)
                        if key in drafts:
                            d = drafts[key]
                            st.code(f"To: {l['email']}\nSubject: {d['subject']}\n\n{d['body']}", language=None, wrap_lines=True)
                            st.caption("Use the copy button in the corner. Fill in the parts in [brackets] before sending.")
                    if t != "skip":
                        st.caption(f"Score: {l['score']} of 100")

with st.expander("How we find and rank leads"):
    st.markdown("""
We search Google Maps for the kinds of businesses you picked, near your city. For each one we open its website
(home page, plus Contact and About pages) and collect the email addresses written there. We check that each email’s
domain can actually receive mail. Claude reads the About page to find the owner’s name, and is never allowed to use a
name that isn’t written on the page.

**Skipped:** closed businesses, chains (if you asked), places outside your area, and your do-not-contact list.
**Need an email:** real businesses where we couldn’t find an email yet. Call them, or check their website.

Everyone else gets points out of 100: a personal company email 30 (shared inbox 15, free account 10), the owner’s
name 20 (any name 10), a Google review in the last 3 months 20 (last year 10), a website 10, a phone number 5, and
15 if they show a sign that they need you. **Contact now** is 70 or more, **Worth a try** is 50–69.

We never send anything. You review and send every email yourself. US law (CAN-SPAM) requires that you say who you
are, include your business address, and offer a way to opt out: every draft includes these.
""")
