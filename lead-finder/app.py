"""Lead Finder: find small businesses to sell to. Built for owners with no technical background."""
import csv
import html
import io
import os
import time

import pandas as pd
import streamlit as st

import finder

st.set_page_config(page_title="Lead Finder", page_icon="🎯", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');
:root { --ink:#16201C; --muted:#5E6B66; --line:#E1E6E0; --bg:#F3F5F2; --card:#FFFFFF;
        --green:#1F6F54; --green-soft:#E3F1EA; --amber:#B7791F; --amber-soft:#FBF1DE;
        --blue:#35609C; --blue-soft:#E7EEF8; --grey:#7B8580; --grey-soft:#EEF0EE; --red:#A8432F; --red-soft:#F8E6E1; }
html, body, [class*="css"], .stMarkdown, .stButton button, input, textarea, label, p, div {
  font-family: 'Plus Jakarta Sans', ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif !important; }
.stApp { background: var(--bg); }
.block-container { max-width: 1080px; padding-top: 2.5rem; padding-bottom: 4rem; }
header[data-testid="stHeader"] { background: transparent; }

/* hero */
.lf-hero { display:grid; grid-template-columns: 1.5fr 1fr; gap: 2.5rem; align-items:end; margin-bottom: 1.8rem; }
.lf-h1 { font-size: clamp(2.3rem, 4.6vw, 3.4rem); line-height: 1.02; font-weight: 800; letter-spacing: -0.035em;
              color: var(--ink); margin: 0 0 .8rem; padding: 0; }
.lf-hero p { color: var(--muted); font-size: 1.08rem; line-height: 1.55; margin: 0; max-width: 34rem; }
.lf-how { list-style:none; margin:0; padding:0; border-left: 2px solid var(--line); }
.lf-how li { padding: .35rem 0 .35rem 1rem; color: var(--muted); font-size: .95rem; }
.lf-how b { color: var(--ink); font-weight: 700; }
@media (max-width: 760px) { .lf-hero { grid-template-columns: 1fr; gap: 1.2rem; } }

/* step panels */
[class*="st-key-panel"] { background: var(--card); border: 1px solid var(--line); border-radius: 18px; padding: 1.4rem 1.5rem 1.2rem; }
.lf-step { display:flex; gap:.7rem; align-items:center; margin-bottom:.2rem; }
.lf-num { width: 1.75rem; height: 1.75rem; border-radius: 50%; background: var(--green); color: #fff; display:grid;
          place-items:center; font-weight: 700; font-size: .85rem; flex: none; }
.lf-title { font-size: 1.22rem; font-weight: 700; color: var(--ink); }
.lf-hint { color: var(--muted); font-size: .93rem; margin: .1rem 0 .6rem 2.4rem; }

.stButton button, .stFormSubmitButton button, .stLinkButton a { border-radius: 10px !important; font-weight: 600 !important; }
.stFormSubmitButton button { padding: .75rem 1rem !important; font-size: 1.02rem !important; }

/* results */
.lf-results-h { display:flex; justify-content:space-between; align-items:baseline; flex-wrap:wrap; gap:.5rem; margin: 2.2rem 0 .8rem; }
.lf-h2 { font-size: 1.9rem; font-weight: 800; letter-spacing: -0.02em; color: var(--ink); }
.lf-results-sub { color: var(--muted); font-size: .92rem; }
.lf-stats { display:grid; grid-template-columns: repeat(4, 1fr); gap: .8rem; margin-bottom: 1rem; }
.lf-stat { background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: .9rem 1rem; }
.lf-stat b { display:block; font-size: 2rem; font-weight: 800; line-height: 1; font-variant-numeric: tabular-nums; }
.lf-stat span { color: var(--muted); font-size: .88rem; }
.lf-stat.now b { color: var(--green); } .lf-stat.try b { color: var(--amber); }
.lf-stat.need b { color: var(--blue); } .lf-stat.aside b { color: var(--grey); }
@media (max-width: 640px) { .lf-stats { grid-template-columns: repeat(2, 1fr); } }
.lf-legend { color: var(--muted); font-size: .85rem; margin: .3rem 0 1rem; }
.lf-dot { display:inline-block; width:.6rem; height:.6rem; border-radius:50%; margin: 0 .3rem 0 .9rem; }

/* lead cards */
[class*="st-key-card"] { background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: 1.2rem 1.3rem 1rem; }
.lf-card-head { display:flex; gap: 1rem; align-items:center; }
.lf-ring { --p:0; --c:var(--green); width: 3.6rem; height: 3.6rem; border-radius: 50%; flex:none; display:grid; place-items:center;
           background: conic-gradient(var(--c) calc(var(--p) * 1%), var(--grey-soft) 0); }
.lf-ring span { width: 2.8rem; height: 2.8rem; border-radius: 50%; background: var(--card); display:grid; place-items:center;
                font-weight: 800; font-size: 1.05rem; color: var(--ink); font-variant-numeric: tabular-nums; }
.lf-name { font-size: 1.22rem; font-weight: 700; color: var(--ink); line-height: 1.2; }
.lf-person { color: var(--ink); font-size: .96rem; margin-top: .15rem; }
.lf-person em { color: var(--muted); font-style: normal; }
.lf-badge { display:inline-block; font-size: .74rem; font-weight: 700; padding: .12rem .55rem; border-radius: 999px; margin-bottom: .25rem; }
.lf-badge.now { background: var(--green-soft); color: var(--green); } .lf-badge.try { background: var(--amber-soft); color: var(--amber); }
.lf-badge.need_email { background: var(--blue-soft); color: var(--blue); } .lf-badge.later { background: var(--grey-soft); color: var(--grey); }
.lf-badge.skip { background: var(--red-soft); color: var(--red); }
.lf-what { color: var(--muted); font-size: .93rem; margin: .7rem 0 0; }
.lf-hook { margin: .7rem 0 0; padding: .55rem .8rem; background: var(--green-soft); border-radius: 10px; color: var(--ink);
           font-size: .96rem; line-height: 1.45; }
.lf-hook small { display:block; color: var(--green); font-weight: 700; font-size: .74rem; margin-bottom: .1rem; }
.lf-next { font-weight: 700; color: var(--ink); margin: .8rem 0 .4rem; }
.lf-email { display:flex; flex-wrap:wrap; gap:.5rem; align-items:center; margin: .2rem 0 .3rem; }
.lf-email code { background: var(--grey-soft); color: var(--ink); padding: .25rem .55rem; border-radius: 8px; font-size: .92rem; }
.lf-ver { font-size: .8rem; font-weight: 700; padding: .15rem .55rem; border-radius: 999px; }
.lf-ver.valid { background: var(--green-soft); color: var(--green); }
.lf-ver.domain_ok { background: var(--blue-soft); color: var(--blue); }
.lf-ver.accepts_all, .lf-ver.unknown { background: var(--amber-soft); color: var(--amber); }
.lf-check { background: var(--amber-soft); border-radius: 10px; padding: .5rem .8rem; font-size: .9rem; color: #5C4310; margin: .5rem 0; }
.lf-skip-row { padding: .55rem 0; border-bottom: 1px solid var(--line); font-size: .95rem; }
.lf-skip-row:last-child { border-bottom: none; }
.lf-skip-row span { color: var(--muted); }
</style>
""", unsafe_allow_html=True)


def secret(name: str) -> str:
    try:
        v = st.secrets.get(name, "")
    except Exception:  # no secrets file
        v = ""
    return v or os.environ.get(name, "")


GOOGLE_KEY = secret("GOOGLE_MAPS_API_KEY")
CLAUDE_KEY = secret("ANTHROPIC_API_KEY")
CLAUDE_MODEL = secret("CLAUDE_MODEL") or "claude-sonnet-5-5"
RING = {"now": "var(--green)", "try": "var(--amber)", "need_email": "var(--blue)", "later": "var(--grey)", "skip": "var(--red)"}
MAP_COLOR = {"now": "#1F6F54", "try": "#B7791F", "need_email": "#35609C", "later": "#9AA39E"}
e = html.escape


@st.cache_resource
def claude_client(key: str):
    if not key:
        return None
    import anthropic
    return anthropic.Anthropic(api_key=key)


@st.cache_resource
def result_cache():
    """Same answers within an hour -> instant results. Good for demos, kinder to the free map servers."""
    return {}


def find_with_cache(profile: dict, how_many: int, progress, log):
    key = (repr(sorted(profile.items())), how_many, bool(CLAUDE_KEY), bool(GOOGLE_KEY))
    hit = result_cache().get(key)
    if hit and time.time() - hit[0] < 3600:
        log("Same search as earlier, so these are the saved results.")
        return hit[1]
    res = finder.find_leads(profile, limit=how_many, google_key=GOOGLE_KEY, claude_client=claude_client(CLAUDE_KEY),
                            claude_model=CLAUDE_MODEL, progress=progress, log=log)
    result_cache()[key] = (time.time(), res)
    return res


def step(n, title, hint=""):
    st.markdown(f"<div class='lf-step'><div class='lf-num'>{n}</div><div class='lf-title'>{e(title)}</div></div>"
                + (f"<p class='lf-hint'>{e(hint)}</p>" if hint else ""), unsafe_allow_html=True)


# ---------------------------------------------------------------- hero
st.markdown(f"""
<div class="lf-hero">
  <div>
    <div class="lf-h1">Find your next customers.</div>
    <p>Real local businesses, an email that works, and a reason to reach out, ranked so you know who to contact first.</p>
  </div>
  <ol class="lf-how">
    <li><b>Search</b> {'Google Maps' if GOOGLE_KEY else 'a free public map'} near you</li>
    <li><b>Find and verify</b> emails on each business’s own website</li>
    <li><b>{'Let Claude read' if CLAUDE_KEY else 'Read'}</b> each site to judge fit and find the owner</li>
  </ol>
</div>
""", unsafe_allow_html=True)

DEFAULTS = {"radius": "10 miles", "deciders": ["The owner"], "avoid": ["Chains and franchises"], "how_many": 20,
            "types": [], "signals": [], "sell": "", "types_other": "", "city": "", "dnc": ""}
EXAMPLE_TEXT = "I sell software that speeds up invoice and bookkeeping reviews to small accounting firms in Seattle, WA."
EXAMPLE = {"sell": "software that speeds up invoice and bookkeeping reviews", "types": ["Accounting and bookkeeping firms"],
           "types_other": "", "city": "Seattle, WA", "radius": "10 miles", "deciders": ["The owner"],
           "signals": [], "avoid": ["Chains and franchises"], "how_many": 20}
for k, v in DEFAULTS.items():
    st.session_state.setdefault(k, v)

# ---------------------------------------------------------------- step 1
if CLAUDE_KEY:
    with st.container(key="panel_describe"):
        step(1, "Who do you sell to?", "Say it in a sentence. We’ll fill in the details for you.")
        desc = st.text_area("Your business in a sentence", key="desc", label_visibility="collapsed", height=90,
                            placeholder=f"Example: {EXAMPLE_TEXT}")
        c1, c2, _ = st.columns([1.3, 1, 2])
        if c1.button("Fill in the details for me", type="primary", width="stretch"):
            if not (desc or "").strip():
                st.error("Write a sentence about what you sell and who buys it first.")
            else:
                with st.spinner("Reading your description…"):
                    try:
                        st.session_state.update(finder.claude_understand(claude_client(CLAUDE_KEY), CLAUDE_MODEL, desc))
                        st.session_state["understood"] = True
                        st.rerun()
                    except Exception:
                        st.error("Claude couldn’t read that just now. Fill in the details below yourself.")
        c2.button("Try an example", width="stretch",
                  on_click=lambda: st.session_state.update({**EXAMPLE, "desc": EXAMPLE_TEXT, "understood": True}))
        if st.session_state.get("understood"):
            st.success("Filled in. Check the details below and change anything that’s not right.")
    st.write("")

# ---------------------------------------------------------------- step 2
with st.container(key="panel_details"):
    with st.form("questions", border=False):
        step(2 if CLAUDE_KEY else 1, "Check the details" if CLAUDE_KEY else "Tell us about your customers")
        if not CLAUDE_KEY:
            st.form_submit_button("Try an example", on_click=lambda: st.session_state.update(EXAMPLE))
        sell = st.text_input("What do you sell?", key="sell", placeholder="Example: bookkeeping software")
        types = st.pills("What kinds of businesses buy from you?", list(finder.TYPES), selection_mode="multi", key="types")
        types_other = st.text_input("Something else? Type it here.", key="types_other", placeholder="Example: dog groomers")
        c1, c2 = st.columns(2)
        city = c1.text_input("City to search around", key="city", placeholder="Example: Seattle, WA")
        with c2:
            radius = st.pills("How far from there?", list(finder.RADIUS_MILES), selection_mode="single", key="radius")
        deciders = st.pills("Who do you usually talk to?", list(finder.DECIDER_WORDS), selection_mode="multi",
                            key="deciders")
        with st.expander("More options"):
            signals = st.pills("What tells you a business needs you?", finder.SIGNALS if GOOGLE_KEY else ["No website"],
                               selection_mode="multi", key="signals")
            avoid = st.pills("Who should we skip?", ["Chains and franchises"], selection_mode="multi", key="avoid")
            how_many = st.select_slider("How many businesses should we look at?", [20, 40, 60], key="how_many",
                                        help="More takes a little longer.")
            dnc = st.text_area("Businesses you never want to contact (one per line)", key="dnc")
        go = st.form_submit_button("Find leads", type="primary", width="stretch")

if go:
    profile = {"sell": sell.strip(), "types": types or [], "types_other": types_other.strip(), "city": city.strip(),
               "radius": radius or "10 miles", "deciders": deciders or ["The owner"], "signals": signals or [],
               "avoid": avoid or [], "do_not_contact": (dnc or "").splitlines()}
    if not profile["sell"]:
        st.error("Tell us what you sell. We use it to judge fit and write your emails.")
    elif not profile["types"] and not profile["types_other"]:
        st.error("Pick at least one kind of business, or type one in.")
    elif not profile["city"]:
        st.error("Tell us which city to search around.")
    else:
        t0 = time.time()
        with st.status("Finding leads. This usually takes 30 to 60 seconds…", expanded=True) as status:
            bar = st.progress(0.0)
            try:
                result = find_with_cache(profile, how_many, lambda m, f: bar.progress(min(1.0, f), text=m),
                                         lambda text: st.write("✓ " + text))
                st.session_state["result"] = {**result, "seconds": round(time.time() - t0)}
                st.session_state["profile"] = profile
                st.session_state["drafts"], st.session_state["manual"] = {}, {}
                status.update(label=f"Done in {round(time.time() - t0)} seconds", state="complete", expanded=False)
            except finder.SearchError as err:
                status.update(label="Couldn’t finish the search", state="error")
                st.error(str(err))


# ---------------------------------------------------------------- results
def current_leads():
    res, profile = st.session_state["result"], st.session_state["profile"]
    manual = st.session_state.setdefault("manual", {})
    out = [finder.with_manual_email(l, manual[l["id"]], profile, verify=finder.verify_email) if l["id"] in manual else l
           for l in res["leads"]]
    return sorted(out, key=lambda l: (finder.TIER_ORDER[l["tier"]], -l["score"], l["business_name"]))


def add_email(lead_id):
    v = (st.session_state.get(f"add-{lead_id}") or "").strip()
    if v and finder.EMAIL_RE.fullmatch(v.lower()):
        st.session_state["manual"][lead_id] = v


def card_html(l):
    who = ""
    if l.get("contact_name"):
        who = f"<div class='lf-person'>{e(l['contact_name'])}" + \
              (f" <em>· {e(l['contact_title'])}</em>" if l.get("contact_title") else "") + "</div>"
    what = "  ·  ".join(e(x) for x in [l.get("what_they_do"), l.get("address")] if x)
    hook = f"<div class='lf-hook'><small>Why they might need you</small>{e(l['hook'])}</div>" if l.get("hook") else ""
    email = ""
    if l.get("email"):
        stat = l.get("email_status") or "unknown"
        label = finder.EMAIL_STATUS.get(stat, ("", ""))[0]
        mark = "✓ " if stat == "valid" else ""
        email = f"<div class='lf-email'><code>{e(l['email'])}</code><span class='lf-ver {stat}' " \
                f"title='{e(l.get('email_detail', ''))}'>{mark}{e(label)}</span></div>"
    check = f"<div class='lf-check'><b>Check before you send:</b> {e(' '.join(l['check']))}</div>" if l["check"] else ""
    return f"""
<div class="lf-card-head">
  <div class="lf-ring" style="--p:{l['score']}; --c:{RING[l['tier']]}"><span>{l['score']}</span></div>
  <div><span class="lf-badge {l['tier']}">{e(finder.TIER_LABEL[l['tier']])}</span>
       <div class="lf-name">{e(l['business_name'])}</div>{who}</div>
</div>
{f"<div class='lf-what'>{what}</div>" if what else ""}{hook}
<div class="lf-next">{e(l['next'])}</div>{email}{check}"""


def lead_card(l, profile, i):
    with st.container(key=f"card_{i}_{l['id']}".replace(":", "_")):
        st.markdown(card_html(l), unsafe_allow_html=True)
        b1, b2, b3, _ = st.columns([1.4, 1, 1, 1.2])
        if l["tier"] in ("now", "try") and l.get("email"):
            if b1.button("Write my first email", key=f"btn-{l['id']}-{i}", type="primary", width="stretch"):
                with st.spinner("Writing…"):
                    try:
                        mail = finder.claude_email(claude_client(CLAUDE_KEY), CLAUDE_MODEL, profile, l)
                    except Exception:
                        mail = None
                st.session_state["drafts"][l["id"]] = mail or finder.template_email(profile, l)
        if l.get("website"):
            b2.link_button("Website", l["website"], width="stretch")
        if l.get("maps_url"):
            b3.link_button("Map", l["maps_url"], width="stretch")
        d = st.session_state["drafts"].get(l["id"])
        if d:
            st.code(f"To: {l['email']}\nSubject: {d['subject']}\n\n{d['body']}", language=None, wrap_lines=True)
            st.caption("Copy it with the button in the corner, fill in the [brackets], and send it from your own email.")
        with st.expander("Why this ranking"):
            st.markdown("\n".join(f"- {x}" for x in l["why"] + l.get("improve", [])) or "No details.")
            if (l.get("site") or {}).get("pages"):
                st.caption("Pages we read: " + ", ".join(l["site"]["pages"]))


if st.session_state.get("result"):
    res, profile = st.session_state["result"], st.session_state["profile"]
    leads = current_leads()
    g = {t: [l for l in leads if l["tier"] == t] for t in finder.TIER_LABEL}
    aside = g["later"] + g["skip"]
    verified = sum(1 for l in leads if l.get("email_status") == "valid")
    st.markdown(f"""
<div class="lf-results-h"><div class="lf-h2">Your leads</div>
<div class="lf-results-sub">{len(leads)} businesses from {e(res['source'])} in {res.get('seconds', 0)} seconds
{f'· {verified} mailbox{"es" if verified != 1 else ""} confirmed' if verified else ''}</div></div>
<div class="lf-stats">
  <div class="lf-stat now"><b>{len(g['now'])}</b><span>Contact now</span></div>
  <div class="lf-stat try"><b>{len(g['try'])}</b><span>Worth a try</span></div>
  <div class="lf-stat need"><b>{len(g['need_email'])}</b><span>Need an email</span></div>
  <div class="lf-stat aside"><b>{len(aside)}</b><span>Set aside</span></div>
</div>""", unsafe_allow_html=True)

    pts = [{"lat": l["latlon"][0], "lon": l["latlon"][1], "color": MAP_COLOR[l["tier"]]}
           for l in leads if l.get("latlon") and l["tier"] in MAP_COLOR]
    if pts:
        st.map(pd.DataFrame(pts), latitude="lat", longitude="lon", color="color", size=70, height=280)
        st.markdown("<div class='lf-legend'>"
                    + "".join(f"<span class='lf-dot' style='background:{c}'></span>{n}" for n, c in
                              [("Contact now", "#1F6F54"), ("Worth a try", "#B7791F"), ("Need an email", "#35609C"),
                               ("Later", "#9AA39E")]) + "</div>", unsafe_allow_html=True)

    t_top, t_need, t_all, t_skip = st.tabs([f"Best leads  {len(g['now']) + len(g['try'])}",
                                            f"Need an email  {len(g['need_email'])}", "Table",
                                            f"Set aside  {len(aside)}"])
    with t_top:
        best = g["now"] + g["try"]
        if not best:
            st.info("No leads with an email yet. Open **Need an email**: call them, add the email, and they’ll move here.")
        for i, l in enumerate(best):
            lead_card(l, profile, i)
    with t_need:
        st.caption("Real businesses with no email on their website. Call them or check their site, paste the email you "
                   "find, and we’ll verify it and move the lead to Best leads.")
        for i, l in enumerate(g["need_email"]):
            with st.container(key=f"card_need_{i}"):
                st.markdown(f"<div class='lf-name'>{e(l['business_name'])}</div><div class='lf-what'>"
                            f"{e(l.get('phone') or 'No phone listed')}{'  ·  ' + e(l['address']) if l.get('address') else ''}"
                            f"</div>", unsafe_allow_html=True)
                c1, c2 = st.columns([3, 1])
                c1.text_input("Found their email? Paste it here.", key=f"add-{l['id']}", on_change=add_email,
                              args=(l["id"],), placeholder="name@business.com")
                if l.get("website"):
                    c2.link_button("Website", l["website"], width="stretch")
                if l.get("check"):
                    st.caption(" ".join(l["check"]))
    with t_all:
        df = pd.DataFrame([{"Priority": finder.TIER_LABEL[l["tier"]], "Business": l["business_name"],
                            "Owner": l.get("contact_name", ""), "Email": l.get("email", ""),
                            "Email check": finder.EMAIL_STATUS.get(l.get("email_status"), ("",))[0] if l.get("email") else "",
                            "Phone": l.get("phone", ""), "Score": l["score"], "Why they might need you": l.get("hook", ""),
                            "Website": l.get("website") or None} for l in leads])
        st.dataframe(df, hide_index=True, width="stretch", column_config={
            "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
            "Website": st.column_config.LinkColumn("Website", display_text="Open")})
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=finder.CSV_COLUMNS)
        w.writeheader()
        w.writerows(finder.to_rows(leads))
        st.download_button("Download as a spreadsheet", buf.getvalue(), "leads.csv", "text/csv")
    with t_skip:
        with st.container(key="card_aside"):
            if not aside:
                st.write("Nothing set aside.")
            st.markdown("".join(f"<div class='lf-skip-row'><span class='lf-badge {l['tier']}'>"
                                f"{e(finder.TIER_LABEL[l['tier']])}</span> <b>{e(l['business_name'])}</b><br>"
                                f"<span>{e(l['next'])}</span></div>" for l in aside), unsafe_allow_html=True)

st.write("")
with st.expander("How Lead Finder works"):
    st.markdown(f"""
1. **Search.** We look on {'Google Maps' if GOOGLE_KEY else 'OpenStreetMap, a free public map,'} for the kinds of businesses you picked near your city, and set aside chains, closed businesses and places outside your area.
2. **Find emails.** We open each business’s website (home, Contact and About pages) and collect the emails written there. Websites that are up for sale are treated as a sign the business closed.
3. **Verify emails.** For each email we check the format, that it isn’t a throwaway address, that the domain is set up to receive email, and, where the mail server allows it, that the mailbox exists. We never send anything. Addresses that fail are left out.
4. **Read and judge.** {'Claude reads each website to find the owner’s name, what the business does, and how likely it is to need what you sell. It may only use names written on the site.' if CLAUDE_KEY else 'We look for the owner’s name on the About page.'}
5. **Rank.** Points out of 100: personal company email 30 (shared inbox 15, free account 10), confirmed mailbox 5, owner’s name 20 (any name 10), recent Google review 20, website 10, phone 5, strong fit 15. Contact now is 70 or more, Worth a try 50–69. Weak fits go to Later.

You review and send every email yourself. Every draft says who you are, leaves space for your business address, and lets people opt out, as US law (CAN-SPAM) requires.
""")
