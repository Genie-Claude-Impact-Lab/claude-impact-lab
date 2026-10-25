"""Find small-business leads.

1. Search for the kinds of businesses the owner sells to: Google Maps (Places API, has reviews), TomTom
   (free tier, no card, no reviews) or OpenStreetMap (free, fewer results, no reviews).
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
from urllib.parse import quote, quote_plus, unquote, urljoin, urlparse

import requests

UA = "LeadFinder/1.0 (small-business lead research; github.com/Leadline-Claude-Impact-Lab/claude-impact-lab)"

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
ANYWHERE = "Anywhere in the US"
RADIUS_MILES = {"5 miles": 5, "10 miles": 10, "25 miles": 25, ANYWHERE: None}
FREE_MAP_WIDEST = 50   # the free map can't search the whole country, so "anywhere" means this far around the city
DECIDER_WORDS = {
    "The owner": ["owner", "founder", "co-founder", "president", "ceo", "principal", "proprietor", "partner", "managing member"],
    "A founder": ["founder", "co-founder", "ceo"],
    "Business development": ["business development", "partnerships", "bd ", "growth"],
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


def google_search(query: str, key: str, center, radius_mi, limit: int) -> list[dict]:
    body = {"textQuery": query, "pageSize": min(20, limit), "regionCode": "US"}
    if center and radius_mi:
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


# ---------------------------------------------------------------- search: TomTom
TOMTOM_URL = "https://api.tomtom.com/search/2/poiSearch/{query}.json"
SOURCE_LABEL = {"google": "Google Maps", "tomtom": "TomTom", "osm": "OpenStreetMap"}


def pick_source(google_key: str = "", tomtom_key: str = "", preferred: str = "") -> str:
    """Which map to search. `preferred` (the MAP_SOURCE setting) wins if its key is present; otherwise
    Google (it has reviews), then TomTom, then the free OpenStreetMap."""
    pref = (preferred or "").strip().lower()
    if pref == "google" and google_key:
        return "google"
    if pref == "tomtom" and tomtom_key:
        return "tomtom"
    if pref in ("osm", "openstreetmap"):
        return "osm"
    if google_key:
        return "google"
    if tomtom_key:
        return "tomtom"
    return "osm"


def _site_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    return url if re.match(r"https?://", url, re.I) else "https://" + url


def parse_tomtom(r: dict) -> dict:
    """One TomTom search result -> a lead. TomTom has no reviews, ratings or open/closed flag."""
    poi, addr, pos = r.get("poi") or {}, r.get("address") or {}, r.get("position") or {}
    industry = ""
    for c in poi.get("classifications") or []:
        names = c.get("names") or []
        if names and names[0].get("name"):
            industry = names[0]["name"]
            break
    industry = (industry or "").strip()
    name, address = (poi.get("name") or "").strip(), (addr.get("freeformAddress") or "").strip()
    return {
        "id": "t:" + str(r.get("id", "")),
        "business_name": name,
        "address": address,
        "industry": industry[:1].upper() + industry[1:],
        "website": _site_url(poi.get("url", "")),
        "phone": (poi.get("phone") or "").strip(),
        "rating": None, "review_count": None, "last_review_date": "",
        "status": "open",
        "maps_url": "https://www.google.com/maps/search/?api=1&query=" + quote_plus(f"{name} {address}".strip()),
        "latlon": (pos["lat"], pos["lon"]) if "lat" in pos and "lon" in pos else None,
        "is_chain": bool(poi.get("brands")),
        "found_on": "TomTom",
    }


def tomtom_search(query: str, key: str, center, radius_mi: float, limit: int, get=None) -> list[dict]:
    """Businesses matching `query` within `radius_mi` of `center`, from TomTom's POI search. One request."""
    if not center:
        raise SearchError("We couldn’t find that city. Try writing it like “Seattle, WA”.")
    get = get or requests.get
    params = {"key": key, "lat": f"{center[0]:.5f}", "lon": f"{center[1]:.5f}", "radius": int(radius_mi * 1609.34),
              "limit": max(1, min(100, limit)), "countrySet": "US", "language": "en-US"}
    try:
        r = get(TOMTOM_URL.format(query=quote(query, safe="")), params=params, timeout=20)
    except requests.RequestException:
        raise SearchError("We couldn’t reach TomTom. Check your internet connection and try again.")
    if r.status_code != 200:
        try:
            body = r.json() or {}
            msg = body.get("errorText") or (body.get("detailedError") or {}).get("message") or ""
        except Exception:
            msg = (getattr(r, "text", "") or "")[:200]
        if r.status_code == 403:
            raise SearchError("TomTom refused the search. Either the TomTom key was copied wrong, or this month’s free "
                              f"requests are used up. TomTom said: {msg}")
        if r.status_code == 429:
            raise SearchError("TomTom says we’re searching too fast. Wait a few seconds and try again.")
        if r.status_code == 400:
            raise SearchError(f"TomTom couldn’t understand that search. TomTom said: {msg}")
        raise SearchError(f"TomTom search failed ({r.status_code}). Try again in a minute.")
    return [parse_tomtom(x) for x in (r.json().get("results") or []) if (x.get("poi") or {}).get("name")]


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


def _email_rank(e: str, website: str):
    site, dom = domain_of(website), e.split("@")[1]
    on_site = 0 if site and (dom == site or dom.endswith("." + site)) else 1
    return (on_site, {"personal": 0, "shared": 1, "free": 2}[email_kind(e)], e)


def best_email(emails: list[str], website: str) -> str:
    return sorted(emails, key=lambda e: _email_rank(e, website))[0] if emails else ""


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


# ---------------------------------------------------------------- email verification
SMTP_CHECK = True          # tests switch this off
_smtp_blocked = {"value": None}
DISPOSABLE = {"mailinator.com", "10minutemail.com", "guerrillamail.com", "tempmail.com", "yopmail.com", "trashmail.com"}
EMAIL_STATUS = {
    "valid": ("Mailbox confirmed", "Their mail server says this address exists."),
    "accepts_all": ("Can’t confirm mailbox", "Their mail server accepts any address, so this exact mailbox can’t be confirmed."),
    "domain_ok": ("Domain accepts mail", "Their domain is set up to receive email. The mailbox itself wasn’t checked."),
    "unknown": ("Not checked", "We couldn’t check this email right now."),
    "invalid": ("Doesn’t exist", "This address can’t receive email."),
}


def mx_hosts(domain: str):
    """Mail servers for a domain, best first. [] if none, None if DNS can't be reached."""
    try:
        import dns.resolver
        ans = dns.resolver.resolve(domain, "MX", lifetime=5)
        return [str(r.exchange).rstrip(".") for r in sorted(ans, key=lambda r: r.preference)]
    except ImportError:
        return None
    except Exception as e:
        return [] if type(e).__name__ in ("NXDOMAIN", "NoAnswer") else None


def smtp_probe(email: str, host: str, timeout: float = 6):
    """Ask the mail server whether the mailbox exists, without sending anything.
    Returns (exists: True/False/None, catch_all: True/False/None). None means we couldn't tell."""
    import random
    import smtplib
    import string
    if _smtp_blocked["value"]:
        return None, None
    try:
        with smtplib.SMTP(timeout=timeout) as s:
            s.connect(host, 25)
            _smtp_blocked["value"] = False
            s.ehlo_or_helo_if_needed()
            s.mail("")
            code, _ = s.rcpt(email)
            fake = "zz" + "".join(random.choices(string.ascii_lowercase + string.digits, k=12)) + "@" + email.split("@")[1]
            code2, _ = s.rcpt(fake)
            s.rset()
    except (OSError, smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError) as e:
        if _smtp_blocked["value"] is None and isinstance(e, (TimeoutError, ConnectionRefusedError, OSError)):
            _smtp_blocked["value"] = True     # this server can't reach port 25: stop trying
        return None, None
    except smtplib.SMTPException:
        return None, None
    exists = True if code in (250, 251) else False if code in (550, 551, 553) else None
    catch_all = code2 in (250, 251)
    return exists, catch_all


def verify_email(email: str, has_mx_fn=None, hosts_fn=mx_hosts, probe=smtp_probe) -> dict:
    """Layered check: format -> throwaway domain -> domain receives mail -> mailbox exists."""
    email = (email or "").strip().lower()
    if not EMAIL_RE.fullmatch(email):
        return {"status": "invalid", "detail": "That isn’t a valid email address."}
    dom = email.split("@")[1]
    if dom in DISPOSABLE:
        return {"status": "invalid", "detail": "That’s a throwaway email address."}
    if has_mx_fn is not None:
        ok = has_mx_fn(dom)
        hosts = None
    else:
        hosts = hosts_fn(dom)
        ok = None if hosts is None else bool(hosts)
    if ok is False:
        return {"status": "invalid", "detail": f"{dom} isn’t set up to receive email."}
    if ok is None:
        return {"status": "unknown", "detail": EMAIL_STATUS["unknown"][1]}
    if SMTP_CHECK and hosts:
        exists, catch_all = probe(email, hosts[0])
        if exists is False:
            return {"status": "invalid", "detail": "Their mail server says this mailbox doesn’t exist."}
        if exists and catch_all:
            return {"status": "accepts_all", "detail": EMAIL_STATUS["accepts_all"][1]}
        if exists:
            return {"status": "valid", "detail": EMAIL_STATUS["valid"][1]}
    return {"status": "domain_ok", "detail": EMAIL_STATUS["domain_ok"][1]}


def smtp_was_blocked() -> bool:
    return bool(_smtp_blocked["value"])


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


def claude_understand(client, model: str, description: str) -> dict:
    """Turn 'I sell X to Y in Z' into answers for the guided questions. Only allowed choices are kept."""
    msg = client.messages.create(model=model, max_tokens=500, messages=[{"role": "user", "content": f"""A small business owner described what they sell and who they sell to:
\"\"\"{description}\"\"\"

Fill in their search. Use ONLY these exact choices where a list is given.
types (pick 1-3): {json.dumps(list(TYPES))}
radius (pick 1): {json.dumps(list(RADIUS_MILES))}
deciders (pick 1-2): {json.dumps(list(DECIDER_WORDS))}
signals (pick 0-2): {json.dumps(SIGNALS)}
If their customers don't fit any type, leave types empty and put a short search phrase (like "dog groomer") in types_other.
city: the city and state they mentioned, like "Seattle, WA" ("" if none).
sell: what they sell, as a short phrase that completes "I help businesses like yours with ...".

Return ONLY JSON: {{"sell": "", "types": [], "types_other": "", "city": "", "radius": "", "deciders": [], "signals": []}}"""}])
    d = _json_from("".join(b.text for b in msg.content if b.type == "text"))
    pick = lambda xs, allowed: [x for x in (xs or []) if x in allowed]
    return {"sell": (d.get("sell") or "").strip(), "types": pick(d.get("types"), TYPES)[:3],
            "types_other": (d.get("types_other") or "").strip(), "city": (d.get("city") or "").strip(),
            "radius": d.get("radius") if d.get("radius") in RADIUS_MILES else "10 miles",
            "deciders": pick(d.get("deciders"), DECIDER_WORDS) or ["The owner"], "signals": pick(d.get("signals"), SIGNALS)}


def seller_summary(profile: dict) -> str:
    """What we know about the owner's business and best customers, for judging fit."""
    parts = [f"They sell: {profile.get('sell') or 'their services'}."]
    for key, label in (("problem", "The problem they solve"), ("ideal_customer", "Their ideal customer"),
                       ("best_customers", "Their best current customers")):
        if (profile.get(key) or "").strip():
            parts.append(f"{label}: {profile[key].strip()}")
    return "\n".join(parts)


def claude_read_site(client, model: str, profile: dict, business: str, about_text: str) -> dict:
    """Read a business's website: who runs it, what they do, and how much they might need what the owner sells."""
    msg = client.messages.create(model=model, max_tokens=400, messages=[{"role": "user", "content": f"""You help a small business owner find customers.
{seller_summary(profile)}
Here is text from the website of “{business}”, a possible customer:
\"\"\"{about_text[:5000]}\"\"\"

Answer using ONLY facts written in that text.
- owner_name, owner_title: the owner or most senior person named (empty if nobody is clearly named).
- what_they_do: what this business does, in under 12 words.
- fit: 0 to 100, how likely they are to need what the owner sells.
- hook: one plain sentence (under 25 words) saying why they might need it, pointing to something specific on their website. Empty if there's no real reason.

Return ONLY JSON: {{"owner_name": "", "owner_title": "", "what_they_do": "", "fit": 0, "hook": ""}}"""}])
    d = _json_from("".join(b.text for b in msg.content if b.type == "text"))
    out = {"what_they_do": (d.get("what_they_do") or "").strip(), "hook": (d.get("hook") or "").strip()}
    try:
        out["fit"] = max(0, min(100, int(d.get("fit"))))
    except (TypeError, ValueError):
        out["fit"] = None
    name = (d.get("owner_name") or "").strip()
    if name and name.lower() not in about_text.lower():  # never accept a name that isn't on the page
        out["rejected_name"] = name
    elif name:
        out["owner_name"], out["owner_title"] = name, (d.get("owner_title") or "").strip()
    return out


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
                                      "rating", "review_count", "last_review_date", "website", "what_they_do", "hook")}
    msg = client.messages.create(model=model, max_tokens=600, messages=[{"role": "user", "content": f"""Write a short first sales email from a small business owner to a potential customer.
About the sender: they sell {profile.get('sell','')}.
The business they're writing to: {json.dumps(facts)}
Rules: under 120 words; warm, plain, specific to this business; build on the "hook" if there is one; mention one real detail from the data (never invent facts, never claim to have visited or used the business); one clear ask (a short call or reply); greet by first name if known.
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
        st_ = lead.get("email_status")
        if st_ == "valid":
            pts += 5
            why.append("Mailbox confirmed: their mail server says this address exists.")
        elif st_ == "domain_ok":
            why.append("Their domain accepts email. The mailbox itself wasn’t checked.")
        elif st_ == "accepts_all":
            check.append("Their mail server accepts any address, so we can’t confirm this exact mailbox.")
        elif st_ == "unknown":
            check.append("We couldn’t verify this email. Double-check it before sending.")
        site = domain_of(lead.get("website", ""))
        dom = email.split("@")[1]
        if site and dom not in FREE and dom != site and not dom.endswith("." + site):
            check.append(f"The email ends in {dom}, but their website is {site}. Make sure it’s the same business.")
    else:
        improve.append("Call them and ask for the best email." if lead.get("phone")
                       else "Look them up on Google Maps for a phone number or contact form.")

    name, title = lead.get("contact_name", ""), (lead.get("contact_title") or "").lower()
    words = [w for d in (profile.get("deciders") or ["The owner"]) for w in DECIDER_WORDS.get(d, [])]
    words += [r.strip().lower() for r in profile.get("deciders_other", []) if r.strip()]
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
    fit = lead.get("fit")
    if fit is not None and fit >= 70:
        pts += 15
        why.append(f"Claude thinks they’re a strong fit ({fit} of 100).")
    elif fit is not None and fit < 40:
        why.append(f"Claude thinks they’re a weak fit ({fit} of 100).")
    pts = min(pts, 100)
    first = name.split(" ")[0] if name else "them"
    if skip:
        tier, nxt = "skip", "Skip. " + skip
    elif fit is not None and fit < 40:
        tier, nxt = "later", "Probably not your customer" + (f": they {lead['what_they_do'][0].lower() + lead['what_they_do'][1:]}"
                                                               if lead.get("what_they_do") else ".")
        nxt = nxt if nxt.endswith(".") else nxt + "."
    elif not email:
        tier, nxt = "need_email", ("Call " + lead["phone"] + " and ask for the best email." if lead.get("phone")
                                   else "We couldn’t find an email or phone yet.")
    elif pts >= 70:
        tier, nxt = "now", f"Email {first} first."
    elif pts >= 50:
        tier, nxt = "try", f"Worth a short email to {first} this week."
    else:
        tier, nxt = "later", "Save for later. Start with your Contact now list."
    return {**lead, "score": 0 if skip else pts, "tier": tier, "next": nxt, "why": why, "check": check, "improve": improve}


def with_manual_email(lead: dict, email: str, profile: dict, verify=None) -> dict:
    """The owner found an email themselves (for example by calling). Re-score with it."""
    email = email.strip().lower()
    if not EMAIL_RE.fullmatch(email):
        return lead
    base = {k: v for k, v in lead.items() if k not in ("score", "tier", "next", "why", "check", "improve")}
    base["email"], base["flags"] = email, [f for f in base.get("flags", []) if "email" not in f.lower()]
    v = verify(email) if verify else {"status": "unknown", "detail": ""}
    base["email_status"], base["email_detail"] = v["status"], v["detail"]
    if v["status"] == "invalid":
        base["email"] = ""
        base["flags"].append(f"The email you added didn’t check out: {v['detail']}")
    out = score(base, profile)
    if base["email"]:
        out["why"] = ["You added this email yourself."] + out["why"]
    return out


TIER_ORDER = {"now": 0, "try": 1, "need_email": 2, "later": 3, "skip": 4}
TIER_LABEL = {"now": "Contact now", "try": "Worth a try", "need_email": "Need an email", "later": "Later", "skip": "Skipped"}


# ---------------------------------------------------------------- the whole pipeline
def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def find_leads(profile: dict, limit: int = 40, google_key: str = "", claude_client=None,
               claude_model: str = "claude-sonnet-5-5", progress=lambda msg, frac: None,
               visit=visit_website, mx=has_mx, log=lambda text: None, verify=None, tomtom_key: str = "",
               map_source: str = "") -> dict:
    types = list(profile.get("types", []))
    queries = [q for t in types for q in TYPES.get(t, {}).get("google", [])]
    if profile.get("types_other"):
        queries.append(profile["types_other"].strip())
    if not queries:
        raise SearchError("Pick at least one kind of business.")
    city = (profile.get("city") or "").strip()
    anywhere = profile.get("radius") == ANYWHERE
    src = pick_source(google_key, tomtom_key, map_source)
    if not city and not (anywhere and src == "google"):
        raise SearchError("Tell us which city to search around." if not anywhere else
                          "Searching anywhere in the US needs a Google key. Add a city to search around it instead.")
    radius = RADIUS_MILES.get(profile.get("radius", ""), 10)
    if anywhere and src != "google":
        radius = FREE_MAP_WIDEST
        log(f"{SOURCE_LABEL[src]} can't search the whole country, so we searched {FREE_MAP_WIDEST} miles around {city}.")

    progress("Finding your city…", 0.02)
    center = geocode(city) if city else None

    progress("Searching for businesses…", 0.05)
    if src in ("google", "tomtom"):
        source = SOURCE_LABEL[src]
        per = max(5, math.ceil(limit / len(queries)))
        found = []
        for q in queries:
            if src == "google":
                found += google_search(f"{q} in {city}" if city else f"{q} in the United States", google_key, center, radius, per)
            else:   # one request returns up to 100 results, so ask for a bigger pool and keep the best below
                found += tomtom_search(q, tomtom_key, center, radius, max(per * 3, 40))
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
    log(f"Found {len(leads)} businesses on {source}.")
    names = [norm(l["business_name"]) for l in leads]
    dnc = {x.strip().lower() for x in profile.get("do_not_contact", []) if x.strip()}
    for l in leads:
        if names.count(norm(l["business_name"])) > 1:
            l["is_chain"] = True
        d = miles_between(center, l.get("latlon"))
        l["distance_mi"] = d
        l["outside_area"] = bool(radius) and d is not None and d > radius * 1.15
        l["do_not_contact"] = norm(l["business_name"]) in {norm(x) for x in dnc}
        l["flags"] = []
    leads.sort(key=lambda l: (l["outside_area"], not (l.get("website") or l.get("listed_email")), l.get("distance_mi") or 0))
    leads = leads[: limit]

    gone = sum(1 for l in leads if l["is_chain"] or l["outside_area"] or l.get("status") != "open")
    if gone:
        log(f"Set aside {gone} chains, closed or far-away places.")

    # visit websites in parallel
    todo = [l for l in leads if l.get("website") and not l["do_not_contact"]]
    log(f"Visiting {len(todo)} websites to look for emails…")
    for i, (l, res) in enumerate(_parallel(lambda l: visit(l["website"]), todo, 16, deadline=45)):
        progress(f"Checking websites for emails ({i + 1} of {len(todo)})…", 0.15 + 0.5 * (i + 1) / max(1, len(todo)))
        l["site"] = res if isinstance(res, dict) else {"emails": [], "about_text": "", "pages": [],
                                                       "error": str(res) if isinstance(res, TimeoutError) else "We couldn’t open their website."}

    # pick an email and verify it: format, domain, mailbox. Invalid ones are dropped.
    if verify is None:
        verify = lambda e: verify_email(e, has_mx_fn=None if mx is has_mx else mx)
    for l in leads:
        emails = list((l.get("site") or {}).get("emails", []))
        if l.get("listed_email"):
            emails.append(l["listed_email"].lower())
        l["all_emails"] = sorted(set(emails))
        l["candidates"] = sorted(l["all_emails"], key=lambda e: _email_rank(e, l.get("website", "")))[:3]
        if (l.get("site") or {}).get("error") and not l["site"].get("parked"):
            l["flags"].append(l["site"]["error"])
    checks = [(l, e) for l in leads for e in l["candidates"]]
    if checks:
        log(f"Checking {len(checks)} email addresses are real…")
    results = {}
    for (l, e), res in _parallel(lambda le: verify(le[1]), checks, 12, deadline=40):
        results[(l["id"], e)] = res if isinstance(res, dict) else {"status": "unknown", "detail": EMAIL_STATUS["unknown"][1]}
    for l in leads:
        l["email"], l["email_status"], l["email_detail"] = "", "", ""
        for e in l["candidates"]:
            r = results.get((l["id"], e), {"status": "unknown", "detail": EMAIL_STATUS["unknown"][1]})
            if r["status"] == "invalid":
                l["flags"].append(f"Left out {e}: {r['detail']}")
                continue
            l["email"], l["email_status"], l["email_detail"] = e, r["status"], r["detail"]
            break
        l["email_checked"] = l["email_status"] in ("valid", "domain_ok", "accepts_all")
    if smtp_was_blocked():
        log("Mailbox checks aren’t possible from this server, so we confirmed each email’s domain instead.")

    log(f"Found an email for {sum(1 for l in leads if l['email'])} of them.")

    # Claude reads each website: owner's name, what they do, how much they need what the owner sells
    if claude_client:
        ask = [l for l in leads if (l.get("site") or {}).get("about_text") and not l["do_not_contact"]]
        log(f"Claude is reading {len(ask)} websites to judge fit and find owners’ names…")
        for i, (l, res) in enumerate(_parallel(lambda l: claude_read_site(claude_client, claude_model, profile,
                                                                           l["business_name"], l["site"]["about_text"]),
                                               ask, 6, deadline=60)):
            progress(f"Claude is reading websites ({i + 1} of {len(ask)})…", 0.7 + 0.25 * (i + 1) / max(1, len(ask)))
            if isinstance(res, dict):
                l["contact_name"], l["contact_title"] = res.get("owner_name", ""), res.get("owner_title", "")
                l["fit"], l["hook"], l["what_they_do"] = res.get("fit"), res.get("hook", ""), res.get("what_they_do", "")
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


CSV_COLUMNS = ["priority", "business_name", "next", "hook", "what_they_do", "contact_name", "contact_title", "email",
               "email_status",
               "phone", "website", "address", "rating", "review_count", "last_review_date", "fit", "score", "found_on",
               "maps_url", "why", "check"]


def to_rows(leads: list[dict]) -> list[dict]:
    return [{**{k: l.get(k, "") for k in CSV_COLUMNS}, "priority": TIER_LABEL[l["tier"]],
             "why": " ".join(l.get("why", [])), "check": " ".join(l.get("check", []))} for l in leads]
