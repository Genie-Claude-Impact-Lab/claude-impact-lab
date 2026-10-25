"""Find small-business leads.

1. Search Google Maps (Places API) for the kinds of businesses the owner sells to.
   Without a Google key, fall back to OpenStreetMap (free, fewer results, no reviews).
2. Visit each business's website and collect email addresses from its home, Contact and About pages.
3. Ask Claude to read the About page and pull out the owner's name and title (optional).
4. Check that each email's domain can receive mail, then score and rank every lead.
"""
from __future__ import annotations

import concurrent.futures as cf
import html
import json
import math
import re
import time
from datetime import datetime, timezone
from urllib.parse import unquote, urljoin, urlparse

import requests

UA = "LeadFinder/1.0 (small-business lead research; github.com/karleybrowning/claude-impact-lab)"

# ---------------------------------------------------------------- what owners can pick
TYPES = {
    "Accounting and bookkeeping firms": {"google": ["accounting firm", "bookkeeping service"], "osm": ['office~"^(accountant|tax_advisor)$"']},
    "Consulting firms": {"google": ["consulting firm"], "osm": ['office~"^(consulting)$"']},
    "Staffing and recruiting agencies": {"google": ["staffing agency", "recruiting agency"], "osm": ['office~"^(employment_agency)$"']},
    "Medical and dental clinics": {"google": ["dental clinic", "medical clinic"], "osm": ['amenity~"^(dentist|clinic|doctors)$"']},
    "Law firms": {"google": ["law firm"], "osm": ['office~"^(lawyer)$"']},
    "Contractors and trades": {"google": ["plumber", "electrician", "roofing contractor", "general contractor"],
                               "osm": ['craft~"^(plumber|electrician|roofer|hvac|carpenter|builder|painter)$"']},
    "Restaurants and cafes": {"google": ["restaurant", "cafe"], "osm": ['amenity~"^(restaurant|cafe)$"']},
    "Salons and spas": {"google": ["hair salon", "day spa"], "osm": ['shop~"^(hairdresser|beauty|massage)$"']},
}
RADIUS_MILES = {"Within 5 miles": 5, "Within 10 miles": 10, "Within 25 miles": 25}
DECIDER_WORDS = {
    "The owner": ["owner", "founder", "co-founder", "president", "ceo", "principal", "proprietor", "partner", "managing member"],
    "A manager": ["manager", "director", "gm"],
    "An office manager": ["office manager", "administrator", "office admin"],
    "A marketing person": ["marketing"],
}
SIGNALS = ["No website", "Few reviews", "Lower rating (under 4 stars)", "Busy and well reviewed"]

FREE = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com", "icloud.com", "live.com", "msn.com", "comcast.net", "proton.me", "protonmail.com"}
ROLE = {"info", "contact", "hello", "office", "admin", "sales", "support", "team", "service", "help", "booking", "bookings",
        "enquiries", "inquiries", "reception", "frontdesk", "appointments", "mail", "hr", "jobs", "careers", "billing", "accounts"}
JUNK_DOMAINS = {"example.com", "sentry.io", "wixpress.com", "sentry-next.wixpress.com", "godaddy.com", "squarespace.com",
                "domain.com", "email.com", "yourdomain.com", "yoursite.com", "website.com", "mysite.com", "company.com", "sentry.wixpress.com",
                "afternic.com", "godaddy.com", "sedo.com", "dan.com", "hugedomains.com"}
JUNK_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js", ".ico")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


class SearchError(Exception):
    """A problem the owner should see in plain words."""


# ---------------------------------------------------------------- location
def geocode(city: str):
    """City name -> (lat, lon) using OpenStreetMap's free geocoder. None if not found."""
    try:
        r = requests.get("https://nominatim.openstreetmap.org/search",
                         params={"q": city, "format": "json", "limit": 1, "countrycodes": "us"},
                         headers={"User-Agent": UA}, timeout=15)
        hits = r.json()
        return (float(hits[0]["lat"]), float(hits[0]["lon"])) if hits else None
    except Exception:
        return None


def miles_between(a, b):
    if not a or not b:
        return None
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


# ---------------------------------------------------------------- search: Google Maps
GOOGLE_FIELDS = ",".join("places." + f for f in [
    "id", "displayName", "formattedAddress", "location", "websiteUri", "nationalPhoneNumber", "rating",
    "userRatingCount", "businessStatus", "reviews", "primaryTypeDisplayName", "googleMapsUri"]) + ",nextPageToken"


def parse_google(p: dict) -> dict:
    reviews = p.get("reviews") or []
    dates = sorted((rv.get("publishTime") or "")[:10] for rv in reviews if rv.get("publishTime"))
    status = {"OPERATIONAL": "open", "CLOSED_TEMPORARILY": "temporarily closed",
              "CLOSED_PERMANENTLY": "closed"}.get(p.get("businessStatus", ""), "open")
    loc = p.get("location") or {}
    return {
        "id": "g:" + p.get("id", ""),
        "business_name": (p.get("displayName") or {}).get("text", ""),
        "address": p.get("formattedAddress", ""),
        "industry": (p.get("primaryTypeDisplayName") or {}).get("text", ""),
        "website": p.get("websiteUri", ""),
        "phone": p.get("nationalPhoneNumber", ""),
        "rating": p.get("rating"),
        "review_count": p.get("userRatingCount"),
        "last_review_date": dates[-1] if dates else "",
        "status": status,
        "maps_url": p.get("googleMapsUri", ""),
        "latlon": (loc["latitude"], loc["longitude"]) if "latitude" in loc else None,
        "is_chain": False,
        "found_on": "Google Maps",
    }


def google_search(query: str, key: str, center, radius_mi: float, limit: int) -> list[dict]:
    body = {"textQuery": query, "pageSize": min(20, limit)}
    if center:
        body["locationBias"] = {"circle": {"center": {"latitude": center[0], "longitude": center[1]},
                                           "radius": min(radius_mi * 1609.34, 50000.0)}}
    out, token = [], None
    while len(out) < limit:
        if token:
            body["pageToken"] = token
        r = requests.post("https://places.googleapis.com/v1/places:searchText", json=body, timeout=25,
                          headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": GOOGLE_FIELDS})
        if r.status_code != 200:
            try:
                msg = r.json().get("error", {}).get("message", "")
            except Exception:
                msg = r.text[:200]
            if r.status_code in (400, 403):
                raise SearchError("Google Maps refused the search. Check that the Google key is correct and that "
                                  f"“Places API (New)” is turned on for it. Google said: {msg}")
            raise SearchError(f"Google Maps search failed ({r.status_code}). Try again in a minute.")
        data = r.json()
        out += [parse_google(p) for p in data.get("places", [])]
        token = data.get("nextPageToken")
        if not token:
            break
        time.sleep(1)
    return out[:limit]


# ---------------------------------------------------------------- search: OpenStreetMap (free fallback)
OVERPASS = ["https://overpass-api.de/api/interpreter",
            "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
            "https://overpass.private.coffee/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter"]


def parse_osm(e: dict) -> dict:
    t = e.get("tags", {})
    c = e.get("center") or e
    addr = " ".join(x for x in [t.get("addr:housenumber", ""), t.get("addr:street", "")] if x)
    addr = ", ".join(x for x in [addr, t.get("addr:city", ""), t.get("addr:state", "")] if x)
    return {
        "id": f"o:{e.get('type','')}{e.get('id','')}",
        "business_name": t.get("name", ""),
        "address": addr,
        "industry": (t.get("craft") or t.get("office") or t.get("amenity") or t.get("shop") or "").replace("_", " "),
        "website": t.get("website") or t.get("contact:website", ""),
        "phone": t.get("phone") or t.get("contact:phone", ""),
        "listed_email": t.get("email") or t.get("contact:email", ""),
        "rating": None, "review_count": None, "last_review_date": "",
        "status": "open", "maps_url": f"https://www.openstreetmap.org/{e.get('type','node')}/{e.get('id','')}",
        "latlon": (c.get("lat"), c.get("lon")) if c.get("lat") else None,
        "is_chain": bool(t.get("brand") or t.get("brand:wikidata")),
        "found_on": "OpenStreetMap",
    }


def osm_search(filters: list[str], center, radius_mi: float, limit: int, post=None, pause=time.sleep,
               progress=lambda m, f: None) -> list[dict]:
    """Ask every free map server at the same time and use the first good answer. Retries once."""
    if not center:
        raise SearchError("We couldn’t find that city. Try writing it like “Seattle, WA”.")
    post = post or requests.post
    r_m = int(radius_mi * 1609.34)
    parts = "".join(f'nwr[{f}]["name"](around:{r_m},{center[0]:.5f},{center[1]:.5f});' for f in filters)
    q = f"[out:json][timeout:40];({parts});out center tags {max(limit * 4, 100)};"

    def ask(url):
        r = post(url, data={"data": q}, headers={"User-Agent": UA}, timeout=45)
        if r.status_code != 200:
            raise RuntimeError(f"{r.status_code}")
        return [parse_osm(e) for e in r.json().get("elements", []) if e.get("tags", {}).get("name")]

    errors = []
    for attempt in range(2):
        progress("Searching the free map. This usually takes 10 to 40 seconds…" if not attempt
                 else "The map servers were busy. Trying once more…", 0.05)
        ex = cf.ThreadPoolExecutor(max_workers=len(OVERPASS))
        futs = [ex.submit(ask, u) for u in OVERPASS]
        try:
            for f in cf.as_completed(futs, timeout=50):
                try:
                    return f.result()
                except Exception as e:
                    errors.append(str(e) or type(e).__name__)
        except cf.TimeoutError:
            errors.append("timeout")
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
        if not attempt:
            pause(3)
    raise SearchError("The free map service is busy right now. Wait a minute and press Find leads again. "
                      f"(Errors: {', '.join(errors[-4:])})")


def osm_name_filter(text: str) -> str:
    words = re.sub(r"[^A-Za-z0-9 ]", " ", text).split()
    return f'"name"~"{" ".join(words)}",i' if words else ""


# ---------------------------------------------------------------- websites: emails and About text
def decode_cfemail(hexstr: str) -> str:
    key = int(hexstr[:2], 16)
    return "".join(chr(int(hexstr[i:i + 2], 16) ^ key) for i in range(2, len(hexstr), 2))


def emails_in_html(page: str) -> list[str]:
    found = set()
    for m in re.findall(r"mailto:([^\"'?>\s]+)", page, re.I):
        found.add(unquote(m))
    for h in re.findall(r'data-cfemail="([0-9a-fA-F]+)"', page):
        try:
            found.add(decode_cfemail(h))
        except ValueError:
            pass
    found.update(EMAIL_RE.findall(html.unescape(page)))
    clean = []
    for e in found:
        e = e.strip().strip(".,;:()<>[]'\"").lower()
        dom = e.split("@")[-1]
        if not EMAIL_RE.fullmatch(e) or e.endswith(JUNK_EXT) or dom in JUNK_DOMAINS or len(e) > 80:
            continue
        if re.search(r"@\d+x\.", e) or dom.endswith(".wixpress.com"):
            continue
        clean.append(e)
    return sorted(set(clean))


def page_text(page: str) -> str:
    page = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", page)
    page = re.sub(r"(?s)<[^>]+>", " ", page)
    return re.sub(r"\s+", " ", html.unescape(page)).strip()


def useful_links(page: str, base: str) -> list[str]:
    host = urlparse(base).netloc
    links = []
    for href in re.findall(r'href=["\']([^"\'#]+)', page, re.I):
        if re.search(r"contact|about|team|staff|our-story|who-we-are|leadership|meet", href, re.I):
            u = urljoin(base, href)
            if urlparse(u).netloc == host and u not in links:
                links.append(u)
    links.sort(key=lambda u: 0 if "contact" in u.lower() else 1)
    return links[:3]


def domain_of(url: str) -> str:
    if not url:
        return ""
    if not re.match(r"https?://", url):
        url = "https://" + url
    return urlparse(url).netloc.lower().removeprefix("www.")


PARKED_HOSTS = ("forsale.godaddy.com", "sedo.com", "dan.com", "hugedomains.com", "afternic.com", "parkingcrew.net",
                "bodis.com", "undeveloped.com", "porkbun.com/parked")
PARKED_TEXT = re.compile(r"(this domain (name )?(is|may be) for sale|is for sale|domain is parked|buy this domain|"
                         r"parked free|this domain has expired)", re.I)


def is_parked(final_url: str, page: str) -> bool:
    return any(h in (final_url or "").lower() for h in PARKED_HOSTS) or bool(PARKED_TEXT.search(page[:20000]))


def visit_website(url: str, get=None) -> dict:
    """Fetch home + up to 3 Contact/About pages. Returns emails, About text, pages visited."""
    get = get or (lambda u: requests.get(u, headers={"User-Agent": UA}, timeout=(4, 6)))
    if not re.match(r"https?://", url):
        url = "https://" + url
    out = {"emails": [], "about_text": "", "pages": [], "error": ""}
    try:
        home = get(url)
        if getattr(home, "status_code", 200) >= 400:
            out["error"] = f"Their website returned an error ({home.status_code})."
            return out
        home_html = home.text
        if is_parked(getattr(home, "url", url), home_html):
            out["parked"] = True
            out["error"] = "Their website address is up for sale, so the business may have closed or moved."
            return out
    except Exception:
        out["error"] = "We couldn’t open their website."
        return out
    emails, texts = set(emails_in_html(home_html)), []
    out["pages"].append(url)
    for link in useful_links(home_html, url):
        try:
            p = get(link)
            if getattr(p, "status_code", 200) < 400:
                emails.update(emails_in_html(p.text))
                texts.append(page_text(p.text))
                out["pages"].append(link)
        except Exception:
            continue
    out["emails"] = sorted(emails)
    out["about_text"] = (" ".join(texts) or page_text(home_html))[:6000]
    return out


def email_kind(email: str) -> str:
    local, dom = email.lower().split("@", 1)
    if dom in FREE:
        return "free"
    return "shared" if local in ROLE or local.split(".")[0] in ROLE else "personal"


def best_email(emails: list[str], website: str) -> str:
    site = domain_of(website)

    def rank(e):
        dom = e.split("@")[1]
        on_site = 0 if site and (dom == site or dom.endswith("." + site)) else 1
        return (on_site, {"personal": 0, "shared": 1, "free": 2}[email_kind(e)], e)
    return sorted(emails, key=rank)[0] if emails else ""


_mx_cache: dict = {}


def has_mx(domain: str):
    """True / False if checkable, None if DNS can't be reached."""
    if domain in _mx_cache:
        return _mx_cache[domain]
    try:
        import dns.resolver
        ok = len(dns.resolver.resolve(domain, "MX", lifetime=5)) > 0
    except ImportError:
        ok = None
    except Exception as e:
        ok = False if type(e).__name__ in ("NXDOMAIN", "NoAnswer") else None
    _mx_cache[domain] = ok
    return ok


# ---------------------------------------------------------------- Claude: owner's name from the About page
def _json_from(text: str):
    text = re.sub(r"```(json)?", "", text).strip()
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else {}


def claude_owner(client, model: str, business: str, about_text: str) -> dict:
    if not client or not about_text:
        return {}
    msg = client.messages.create(model=model, max_tokens=300, messages=[{"role": "user", "content": f"""From this text on the website of “{business}”, find the business owner or the most senior person named.
Only use a name that is written in the text. If no person is clearly named, leave fields empty.
Return ONLY JSON: {{"owner_name": "", "owner_title": ""}}

Website text:
\"\"\"{about_text[:5000]}\"\"\""""}])
    data = _json_from("".join(b.text for b in msg.content if b.type == "text"))
    name = (data.get("owner_name") or "").strip()
    if name and name.lower() not in about_text.lower():  # never accept a name that isn't on the page
        return {"rejected_name": name}
    return {"owner_name": name, "owner_title": (data.get("owner_title") or "").strip()}


OWNER_TITLES = r"((?i:co-owner|owner|co-founder|founder|president|ceo|principal|managing partner|managing member|managing director|proprietor|partner))"
_CREDS = r"(?:,? (?:CPA|EA|MBA|JD|DDS|DMD|MD|Esq\.?|PE|CFP|PhD|LCSW|DC|DPT))*"
_NAME = r"([A-Z][a-z]+(?: [A-Z]\.)? [A-Z][a-z]+(?:-[A-Z][a-z]+)?)"
_NOT_NAMES = {"About", "Our", "The", "Meet", "Contact", "Welcome", "Call", "Email", "Read", "Learn"}


def owner_from_text(text: str) -> dict:
    """No-AI fallback: finds 'Maria Lopez, Owner', 'Owner: Maria Lopez' or 'Meet Sam Park, our founder'."""
    patterns = [(_NAME + _CREDS + r",? (?:is )?(?:the |our )?" + OWNER_TITLES + r"\b", 1, 2),
                (OWNER_TITLES + r"\s*[:,\-–]?\s+" + _NAME, 2, 1)]
    for pat, n, t in patterns:
        for m in re.finditer(pat, text):
            name = m.group(n)
            if name.split()[0] not in _NOT_NAMES:
                title = m.group(t)
                return {"owner_name": name, "owner_title": "CEO" if title.lower() == "ceo" else title.title()}
    return {}


def claude_email(client, model: str, profile: dict, lead: dict) -> dict | None:
    if not client:
        return None
    facts = {k: lead.get(k) for k in ("business_name", "contact_name", "contact_title", "address", "industry",
                                      "rating", "review_count", "last_review_date", "website")}
    msg = client.messages.create(model=model, max_tokens=600, messages=[{"role": "user", "content": f"""Write a short first sales email from a small business owner to a potential customer.
About the sender: they sell {profile.get('sell','')}.
The business they're writing to: {json.dumps(facts)}
Rules: under 120 words; warm, plain, specific to this business; mention one real detail from the data (never invent facts, never claim to have visited or used the business); one clear ask (a short call or reply); greet by first name if known.
End with exactly:
[Your name]
[Your business]
[Your business address]

If you’d rather not hear from me, just reply “no thanks” and I won’t email again.
Return ONLY JSON: {{"subject": "", "body": ""}}"""}])
    data = _json_from("".join(b.text for b in msg.content if b.type == "text"))
    return data if data.get("body") else None


def template_email(profile: dict, lead: dict) -> dict:
    first = (lead.get("contact_name") or "").split(" ")[0]
    return {"subject": f"A quick idea for {lead['business_name']}", "body": f"""{'Hi ' + first + ',' if first else 'Hi there,'}

I came across {lead['business_name']} and wanted to reach out. I help businesses like yours with {profile.get('sell') or '[what you do]'}.

Would you be open to a 15-minute call next week?

[Your name]
[Your business]
[Your business address]

If you’d rather not hear from me, just reply “no thanks” and I won’t email again."""}


# ---------------------------------------------------------------- scoring
def days_since(d: str):
    try:
        return (datetime.now(timezone.utc).date() - datetime.strptime(d[:10], "%Y-%m-%d").date()).days
    except (ValueError, TypeError):
        return None


def score(lead: dict, profile: dict) -> dict:
    """Points out of 100 plus a tier, a next step, reasons, warnings and tips. Pure function."""
    why, check, improve = [], list(lead.get("flags", [])), []
    pts, skip = 0, None
    if lead.get("do_not_contact"):
        skip = "On your do-not-contact list."
    elif lead.get("status") == "closed":
        skip = "Google lists it as permanently closed."
    elif lead.get("status") == "temporarily closed":
        skip = "Google lists it as temporarily closed."
    elif lead.get("is_chain") and "Chains and franchises" in profile.get("avoid", []):
        skip = "Looks like a chain or franchise, which you asked us to skip."
    elif (lead.get("site") or {}).get("parked"):
        skip = "Their website address is up for sale, so the business may have closed."
    elif lead.get("outside_area"):
        skip = f"About {lead['distance_mi']:.0f} miles away, outside the area you picked."

    email = lead.get("email", "")
    if email:
        kind = email_kind(email)
        pts += {"personal": 30, "shared": 15, "free": 10}[kind]
        why.append({"personal": "Has a personal email at their company.",
                    "shared": "Only a shared inbox (like info@), so it may not reach the owner.",
                    "free": "Uses a free email account (like Gmail)."}[kind])
        if kind == "free":
            check.append("Free email account: make sure it belongs to this business.")
        site = domain_of(lead.get("website", ""))
        dom = email.split("@")[1]
        if site and dom not in FREE and dom != site and not dom.endswith("." + site):
            check.append(f"The email ends in {dom}, but their website is {site}. Make sure it’s the same business.")
    else:
        improve.append("Call them and ask for the best email." if lead.get("phone")
                       else "Look them up on Google Maps for a phone number or contact form.")

    name, title = lead.get("contact_name", ""), (lead.get("contact_title") or "").lower()
    words = [w for d in (profile.get("deciders") or ["The owner"]) for w in DECIDER_WORDS.get(d, [])]
    if name and any(w in title for w in words):
        pts += 20
        why.append(f"You know who to ask for: {name}{', ' + lead['contact_title'] if lead.get('contact_title') else ''}.")
    elif name:
        pts += 10
        why.append(f"You have a name ({name}), but they may not be the person who decides.")
    else:
        why.append("No contact name found on their website.")
        if email:
            improve.append("Check their About page or their replies to Google reviews for the owner’s name.")

    age = days_since(lead.get("last_review_date", ""))
    if age is not None and age <= 90:
        pts += 20
        why.append(f"Newest Google review is {age} days old, so they’re active.")
    elif age is not None and age <= 365:
        pts += 10
        why.append("Reviewed on Google in the last year.")
    elif lead.get("found_on") == "Google Maps":
        why.append("No Google review in the last year, so they may be less active.")

    if lead.get("website"):
        pts += 10
    if lead.get("phone"):
        pts += 5
        why.append("Has a phone number you can call.")

    signals = profile.get("signals", [])
    rc, rating = lead.get("review_count"), lead.get("rating")
    matched = []
    if "No website" in signals and not lead.get("website"):
        matched.append("has no website")
    if "Few reviews" in signals and rc is not None and rc < 20:
        matched.append(f"has only {rc} reviews")
    if "Lower rating (under 4 stars)" in signals and rating is not None and rating < 4:
        matched.append(f"is rated {rating} stars")
    if "Busy and well reviewed" in signals and rc and rc >= 50 and (rating or 0) >= 4.3:
        matched.append(f"is busy and well reviewed ({rating} stars, {rc} reviews)")
    if matched:
        pts += 15
        why.append("Shows a sign they need you: it " + " and ".join(matched) + ".")

    if lead.get("found_on") != "Google Maps":   # free map: no review data, so 20 points can't be earned
        pts = round(pts * 100 / 80)
    pts = min(pts, 100)
    first = name.split(" ")[0] if name else "them"
    if skip:
        tier, nxt = "skip", "Skip. " + skip
    elif not email:
        tier, nxt = "need_email", ("Call " + lead["phone"] + " and ask for the best email." if lead.get("phone")
                                   else "We couldn’t find an email or phone yet.")
    elif pts >= 70:
        tier, nxt = "now", f"Email {first} first at {email}."
    elif pts >= 50:
        tier, nxt = "try", f"Worth a short email to {first} this week."
    else:
        tier, nxt = "later", "Save for later. Start with your Contact now list."
    return {**lead, "score": 0 if skip else pts, "tier": tier, "next": nxt, "why": why, "check": check, "improve": improve}


TIER_ORDER = {"now": 0, "try": 1, "need_email": 2, "later": 3, "skip": 4}
TIER_LABEL = {"now": "Contact now", "try": "Worth a try", "need_email": "Need an email", "later": "Later", "skip": "Skipped"}


# ---------------------------------------------------------------- the whole pipeline
def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def find_leads(profile: dict, limit: int = 40, google_key: str = "", claude_client=None,
               claude_model: str = "claude-sonnet-5-5", progress=lambda msg, frac: None,
               visit=visit_website, mx=has_mx) -> dict:
    types = list(profile.get("types", []))
    queries = [q for t in types for q in TYPES.get(t, {}).get("google", [])]
    if profile.get("types_other"):
        queries.append(profile["types_other"].strip())
    if not queries:
        raise SearchError("Pick at least one kind of business.")
    city = (profile.get("city") or "").strip()
    if not city:
        raise SearchError("Tell us which city to search around.")
    radius = RADIUS_MILES.get(profile.get("radius", ""), 10)

    progress("Finding your city…", 0.02)
    center = geocode(city)

    progress("Searching for businesses…", 0.05)
    if google_key:
        source = "Google Maps"
        per = max(5, math.ceil(limit / len(queries)))
        found = []
        for q in queries:
            found += google_search(f"{q} in {city}", google_key, center, radius, per)
    else:
        source = "OpenStreetMap"
        filters = [f for t in types for f in TYPES.get(t, {}).get("osm", [])]
        if profile.get("types_other"):
            f = osm_name_filter(profile["types_other"])
            if f:
                filters.append(f)
        if not filters:
            raise SearchError("Pick at least one kind of business from the list.")
        found = osm_search(filters, center, radius, limit, progress=progress)

    # combine duplicates, spot chains (same name at several locations), apply area and do-not-contact
    seen, leads = {}, []
    for l in found:
        k = l["id"] or norm(l["business_name"] + l["address"])
        if k in seen or not l["business_name"]:
            continue
        seen[k] = l
        leads.append(l)
    names = [norm(l["business_name"]) for l in leads]
    dnc = {x.strip().lower() for x in profile.get("do_not_contact", []) if x.strip()}
    for l in leads:
        if names.count(norm(l["business_name"])) > 1:
            l["is_chain"] = True
        d = miles_between(center, l.get("latlon"))
        l["distance_mi"] = d
        l["outside_area"] = d is not None and d > radius * 1.15
        l["do_not_contact"] = norm(l["business_name"]) in {norm(x) for x in dnc}
        l["flags"] = []
    leads.sort(key=lambda l: (l["outside_area"], not (l.get("website") or l.get("listed_email")), l.get("distance_mi") or 0))
    leads = leads[: limit]

    # visit websites in parallel
    todo = [l for l in leads if l.get("website") and not l["do_not_contact"]]
    for i, (l, res) in enumerate(_parallel(lambda l: visit(l["website"]), todo, 16, deadline=45)):
        progress(f"Checking websites for emails ({i + 1} of {len(todo)})…", 0.15 + 0.5 * (i + 1) / max(1, len(todo)))
        l["site"] = res if isinstance(res, dict) else {"emails": [], "about_text": "", "pages": [],
                                                       "error": str(res) if isinstance(res, TimeoutError) else "We couldn’t open their website."}

    # pick an email, check it can receive mail
    for l in leads:
        emails = list((l.get("site") or {}).get("emails", []))
        if l.get("listed_email"):
            emails.append(l["listed_email"].lower())
        l["all_emails"] = sorted(set(emails))
        pick = best_email(l["all_emails"], l.get("website", ""))
        if pick:
            ok = mx(pick.split("@")[1])
            if ok is False:
                l["flags"].append(f"Found {pick}, but that domain can’t receive email, so we left it out.")
                rest = [e for e in l["all_emails"] if e.split("@")[1] != pick.split("@")[1]]
                pick = best_email(rest, l.get("website", ""))
            l["email_checked"] = ok is True
        l["email"] = pick
        if (l.get("site") or {}).get("error") and not l["site"].get("parked"):
            l["flags"].append(l["site"]["error"])

    # ask Claude for the owner's name, only where we have an email and About text
    if claude_client:
        ask = [l for l in leads if l["email"] and (l.get("site") or {}).get("about_text")]
        for i, (l, res) in enumerate(_parallel(lambda l: claude_owner(claude_client, claude_model, l["business_name"],
                                                                       l["site"]["about_text"]), ask, 4)):
            progress(f"Reading About pages for owners’ names ({i + 1} of {len(ask)})…", 0.7 + 0.25 * (i + 1) / max(1, len(ask)))
            if isinstance(res, dict):
                l["contact_name"], l["contact_title"] = res.get("owner_name", ""), res.get("owner_title", "")
                if res.get("rejected_name"):
                    l["flags"].append(f"Ignored the name “{res['rejected_name']}” because it isn’t on their website.")

    else:
        for l in leads:
            text = (l.get("site") or {}).get("about_text", "")
            if l["email"] and text:
                found = owner_from_text(text)
                l["contact_name"], l["contact_title"] = found.get("owner_name", ""), found.get("owner_title", "")

    ranked = sorted((score(l, profile) for l in leads), key=lambda l: (TIER_ORDER[l["tier"]], -l["score"], l["business_name"]))
    progress("Done.", 1.0)
    return {"source": source, "leads": ranked, "center_found": bool(center)}


def _parallel(fn, items, workers, deadline=None):
    """Run fn on items at the same time. Anything slower than `deadline` seconds is reported as an error."""
    ex = cf.ThreadPoolExecutor(max_workers=workers)
    futs = {ex.submit(fn, it): it for it in items}
    done = set()
    try:
        for f in cf.as_completed(futs, timeout=deadline):
            done.add(f)
            try:
                yield futs[f], f.result()
            except Exception as e:  # one bad website never stops the run
                yield futs[f], e
    except cf.TimeoutError:
        for f, it in futs.items():
            if f not in done:
                yield it, TimeoutError("Their website took too long to load.")
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


CSV_COLUMNS = ["priority", "business_name", "next", "contact_name", "contact_title", "email", "phone", "website",
               "address", "rating", "review_count", "last_review_date", "score", "found_on", "maps_url", "why", "check"]


def to_rows(leads: list[dict]) -> list[dict]:
    return [{**{k: l.get(k, "") for k in CSV_COLUMNS}, "priority": TIER_LABEL[l["tier"]],
             "why": " ".join(l.get("why", [])), "check": " ".join(l.get("check", []))} for l in leads]
