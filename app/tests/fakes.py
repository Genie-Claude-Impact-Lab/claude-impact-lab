"""Fake Google Maps, fake websites and a fake Claude, so tests run offline."""
from datetime import datetime, timedelta, timezone

def days_ago(n):
    return (datetime.now(timezone.utc) - timedelta(days=n)).strftime("%Y-%m-%dT%H:%M:%SZ")

SEATTLE = (47.6062, -122.3321)

def place(pid, name, website="", phone="(206) 555-0100", rating=4.6, count=40, review_days=10,
          status="OPERATIONAL", lat=47.61, lon=-122.33, kind="Accountant"):
    return {"id": pid, "displayName": {"text": name}, "formattedAddress": f"1 Main St, Seattle, WA 98101, USA",
            "location": {"latitude": lat, "longitude": lon}, "websiteUri": website, "nationalPhoneNumber": phone,
            "rating": rating, "userRatingCount": count, "businessStatus": status,
            "reviews": [{"publishTime": days_ago(review_days)}, {"publishTime": days_ago(review_days + 200)}],
            "primaryTypeDisplayName": {"text": kind}, "googleMapsUri": f"https://maps.google.com/?cid={pid}"}

PLACES = [
    place("1", "Harbor Bookkeeping", website="https://harborbooks.com"),
    place("2", "Elliott CPA Group", website="https://elliottcpa.com", review_days=200),
    place("3", "Gone Accounting", website="https://gone.com", status="CLOSED_PERMANENTLY"),
    place("4", "TaxChain", website="https://taxchain.com"),
    place("5", "TaxChain", website="https://taxchain.com/seattle2"),
    place("6", "Phone Only Tax", website="", phone="(206) 555-0199", count=8),
    place("7", "Tacoma Ledger", website="https://tacomaledger.com", lat=47.25, lon=-122.44),
    place("8", "Fake Name Books", website="https://fakename.com"),
    place("9", "Old Domain CPA", website="http://olddomaincpa.com"),
]

SITES = {
    "https://harborbooks.com": '<a href="/about-us">About</a><a href="/contact">Contact</a><p>Welcome</p>',
    "https://harborbooks.com/contact": '<a href="mailto:maria@harborbooks.com">Email Maria</a> or info@harborbooks.com',
    "https://harborbooks.com/about-us": "<h1>About</h1><p>Maria Lopez, Owner, founded Harbor Bookkeeping in 2012.</p>",
    "https://elliottcpa.com": '<a href="/contact">Contact</a>',
    # Cloudflare-protected email: hello@elliottcpa.com
    "https://elliottcpa.com/contact": '<a class="__cf_email__" data-cfemail="CFCFA7AAA3A3A0">x</a> office@elliottcpa.com',
    "https://taxchain.com": "corporate@taxchain.com",
    "https://tacomaledger.com": "<p>sam@tacomaledger.com</p>",
    "https://fakename.com": '<a href="/about">About</a> jo@fakename.com',
    "https://fakename.com/about": "<p>We are a friendly team of bookkeepers.</p>",
    "http://olddomaincpa.com": "<h1>olddomaincpa.com is for sale</h1> Get a price in 24 hours",
}

class Resp:
    def __init__(self, status, text="", data=None):
        self.status_code, self.text, self._data = status, text, data
    def json(self):
        return self._data

def fake_get(url, **kw):
    if "nominatim" in url:
        return Resp(200, data=[{"lat": str(SEATTLE[0]), "lon": str(SEATTLE[1])}])
    url = url.rstrip("/")
    if url in SITES:
        return Resp(200, SITES[url])
    return Resp(404, "not found")

def fake_post_factory(places=PLACES, status=200):
    calls = []
    def fake_post(url, json=None, headers=None, **kw):
        calls.append({"url": url, "json": json, "headers": headers})
        if status != 200:
            return Resp(status, data={"error": {"message": "API key not valid."}})
        return Resp(200, data={"places": places})
    fake_post.calls = calls
    return fake_post

class FakeClaude:
    """Answers like Claude would, including one made-up name and one poor fit."""
    def __init__(self):
        self.prompts = []
        self.messages = self

    def create(self, model, max_tokens, messages):
        p = messages[0]["content"]
        self.prompts.append(p)
        if "Write a short first sales email" in p:
            out = '{"subject": "Faster invoice reviews", "body": "Hi Maria,\\n\\nSaw you handle month-end close for small businesses...\\n\\nIf you’d rather not hear from me, just reply “no thanks” and I won’t email again."}'
        elif "described what they sell" in p:
            out = '{"sell": "invoice review software", "types": ["Accounting and bookkeeping firms", "Made Up Type"], "types_other": "", "city": "Seattle, WA", "radius": "25 miles", "deciders": ["The owner"], "signals": []}'
        elif "Fake Name Books" in p:
            out = '{"owner_name": "Jordan Smith", "owner_title": "Owner", "what_they_do": "Bookkeeping", "fit": 75, "hook": ""}'
        elif "Maria Lopez" in p:
            out = '{"owner_name": "Maria Lopez", "owner_title": "Owner", "what_they_do": "Bookkeeping for small businesses", "fit": 88, "hook": "They do monthly bookkeeping for small businesses, so they review lots of invoices."}'
        elif "Tacoma Ledger" in p or "tacomaledger" in p:
            out = '{"owner_name": "", "owner_title": "", "what_they_do": "Payroll", "fit": 60, "hook": ""}'
        else:
            out = '{"owner_name": "", "owner_title": "", "what_they_do": "Sells office furniture", "fit": 20, "hook": ""}'
        return type("M", (), {"content": [type("B", (), {"type": "text", "text": out})()]})()


# ---------------------------------------------------------------- TomTom (shaped like TomTom's documented JSON)
def tomtom_result(rid, name, url="", phone="+1 206-555-0100", brands=None, lat=47.61, lon=-122.33, kind="accountant"):
    return {"type": "POI", "id": rid, "score": 2.5, "dist": 900.0, "info": "search:ta:x",
            "poi": {"name": name, "phone": phone, "url": url, "brands": [{"name": b} for b in (brands or [])],
                    "categorySet": [{"id": 9352}],
                    "classifications": [{"code": "COMPANY", "names": [{"nameLocale": "en-US", "name": kind}]}]},
            "address": {"freeformAddress": "1 Main St, Seattle, WA 98101", "municipality": "Seattle"},
            "position": {"lat": lat, "lon": lon}}


TOMTOM_RESULTS = [
    tomtom_result("t1", "Harbor Bookkeeping", url="harborbooks.com"),
    tomtom_result("t2", "Elliott CPA Group", url="elliottcpa.com"),
    tomtom_result("t3", "Phone Only Tax", url="", phone="+1 206-555-0199"),
    tomtom_result("t4", "TaxChain Seattle", url="taxchain.com", brands=["TaxChain"]),
    tomtom_result("t5", "Old Domain CPA", url="http://olddomaincpa.com"),
    {"type": "POI", "id": "t6", "poi": {"name": ""}, "address": {}, "position": {}},     # no name: must be ignored
]


def fake_get_with_tomtom(results=None, status=200, message="", calls=None):
    """requests.get stand-in: TomTom URLs get TomTom answers, everything else gets the usual fake sites."""
    def get(url, **kw):
        if "api.tomtom.com" in url:
            if calls is not None:
                calls.append({"url": url, "params": kw.get("params")})
            if status != 200:
                return Resp(status, data={"errorText": message, "httpStatusCode": str(status),
                                          "detailedError": {"code": "Err", "message": message}})
            return Resp(200, data={"summary": {"numResults": 5}, "results": TOMTOM_RESULTS if results is None else results})
        return fake_get(url, **kw)
    return get
