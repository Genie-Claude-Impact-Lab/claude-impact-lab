"""TomTom as the map. All offline: TomTom, the websites and Claude are faked in TomTom's documented format."""
import pytest
import requests

import finder
from fakes import Resp, SEATTLE, TOMTOM_RESULTS, fake_get_with_tomtom, tomtom_result

PROFILE = {"sell": "invoice review software", "types": ["Accounting and bookkeeping firms"], "types_other": "",
           "city": "Seattle, WA", "radius": "10 miles", "deciders": ["The owner"], "signals": [],
           "avoid": ["Chains and franchises"], "do_not_contact": []}
VERIFY = lambda e: {"status": "domain_ok", "detail": "ok"}


def search(**kw):
    return finder.tomtom_search("accounting firm", "tt-key", SEATTLE, 10, 40, **kw)


# ---------- reading TomTom's answer
def test_a_result_becomes_a_lead():
    l = finder.parse_tomtom(tomtom_result("abc", "Harbor Bookkeeping", url="www.harborbooks.com", brands=[]))
    assert l["id"] == "t:abc" and l["business_name"] == "Harbor Bookkeeping" and l["found_on"] == "TomTom"
    assert l["website"] == "https://www.harborbooks.com"           # TomTom sends bare domains
    assert l["phone"] == "+1 206-555-0100" and l["industry"] == "Accountant"
    assert l["address"].startswith("1 Main St") and l["latlon"] == (47.61, -122.33)
    assert l["rating"] is None and l["review_count"] is None and l["status"] == "open" and not l["is_chain"]
    assert "google.com/maps/search" in l["maps_url"] and "Harbor+Bookkeeping" in l["maps_url"]


def test_brands_mean_chain_and_missing_fields_do_not_crash():
    assert finder.parse_tomtom(tomtom_result("c", "TaxChain", brands=["TaxChain"]))["is_chain"] is True
    bare = finder.parse_tomtom({"id": 7, "poi": {"name": "Bare"}})
    assert bare["website"] == "" and bare["latlon"] is None and bare["industry"] == ""


def test_https_websites_are_left_alone():
    assert finder._site_url("http://a.com/x") == "http://a.com/x" and finder._site_url("") == ""


# ---------- asking TomTom
def test_request_has_the_documented_shape():
    calls = []
    out = search(get=fake_get_with_tomtom(calls=calls))
    url, params = calls[0]["url"], calls[0]["params"]
    assert url == "https://api.tomtom.com/search/2/poiSearch/accounting%20firm.json"
    assert params["key"] == "tt-key" and params["countrySet"] == "US"
    assert params["radius"] == int(10 * 1609.34) and params["lat"] == "47.60620" and params["lon"] == "-122.33210"
    assert params["limit"] == 40
    assert [l["business_name"] for l in out][:2] == ["Harbor Bookkeeping", "Elliott CPA Group"]
    assert all(l["business_name"] for l in out)                     # the nameless result was dropped


def test_limit_is_capped_at_what_tomtom_allows():
    calls = []
    finder.tomtom_search("x", "k", SEATTLE, 5, 500, get=fake_get_with_tomtom(calls=calls))
    assert calls[0]["params"]["limit"] == 100


def test_search_text_cannot_break_the_url():
    calls = []
    finder.tomtom_search("dog groomers/../?key=evil&x", "k", SEATTLE, 5, 10, get=fake_get_with_tomtom(calls=calls))
    assert "/" not in calls[0]["url"].split("poiSearch/")[1].replace(".json", "")
    assert "?" not in calls[0]["url"]


@pytest.mark.parametrize("status,needle", [(403, "free requests are used up"), (429, "too fast"),
                                           (400, "couldn’t understand"), (500, "(500)")])
def test_problems_are_explained_in_plain_words(status, needle):
    with pytest.raises(finder.SearchError, match=needle):
        search(get=fake_get_with_tomtom(status=status, message="Forbidden"))


def test_403_includes_what_tomtom_said():
    with pytest.raises(finder.SearchError, match="Rate or volume limit exceeded"):
        search(get=fake_get_with_tomtom(status=403, message="Rate or volume limit exceeded"))


def test_network_failure_and_unknown_city_are_explained():
    def down(*a, **k):
        raise requests.ConnectionError("down")
    with pytest.raises(finder.SearchError, match="reach TomTom"):
        search(get=down)
    with pytest.raises(finder.SearchError, match="find that city"):
        finder.tomtom_search("x", "k", None, 5, 10)


# ---------- choosing the map
def test_which_map_is_used():
    p = finder.pick_source
    assert p("", "") == "osm" and p("g", "") == "google" and p("", "t") == "tomtom" and p("g", "t") == "google"
    assert p("g", "t", "tomtom") == "tomtom" and p("g", "t", "osm") == "osm" and p("g", "t", "OSM") == "osm"
    assert p("", "t", "google") == "tomtom"        # preferred map has no key: fall back instead of failing
    assert p("g", "", "tomtom") == "google"


# ---------- the whole search, with TomTom
@pytest.fixture
def offline(monkeypatch):
    calls = []
    monkeypatch.setattr(finder.requests, "get", fake_get_with_tomtom(calls=calls))
    def no_post(*a, **k):
        raise AssertionError("Google and OpenStreetMap must not be asked when a TomTom key is set")
    monkeypatch.setattr(finder.requests, "post", no_post)
    monkeypatch.setattr(finder.time, "sleep", lambda s: None)
    return calls


def run(profile=PROFILE, **kw):
    return finder.find_leads(profile, limit=40, tomtom_key="tt-key", mx=lambda d: True, verify=VERIFY, **kw)


def lead(res, name):
    return next(l for l in res["leads"] if l["business_name"] == name)


def test_search_uses_tomtom_once_per_query_and_asks_for_a_big_pool(offline):
    res = run()
    tt = [c for c in offline if "api.tomtom.com" in c["url"]]
    assert res["source"] == "TomTom" and len(tt) == 2              # accounting firm + bookkeeping service
    assert all(c["params"]["limit"] == 60 for c in tt)             # 3 x the per-query share, still one request each
    assert {c["url"].split("poiSearch/")[1] for c in tt} == {"accounting%20firm.json", "bookkeeping%20service.json"}


def test_tomtom_leads_are_found_ranked_and_filtered(offline):
    res = run()
    harbor = lead(res, "Harbor Bookkeeping")
    assert harbor["email"] == "maria@harborbooks.com" and harbor["contact_name"] == "Maria Lopez"
    assert harbor["found_on"] == "TomTom" and harbor["tier"] == "now"
    assert harbor["score"] == 81                                    # 65 of the 80 possible without reviews, scaled to 100
    assert not any("Google review" in w for w in harbor["why"])     # never claims review facts TomTom can't give
    assert lead(res, "TaxChain Seattle")["tier"] == "skip"          # TomTom brand = chain
    assert lead(res, "Old Domain CPA")["tier"] == "skip"            # parked website
    assert lead(res, "Phone Only Tax")["tier"] == "need_email"
    assert "+1 206-555-0199" in lead(res, "Phone Only Tax")["next"]


def test_same_business_from_two_queries_appears_once(offline):
    res = run()
    assert sum(l["business_name"] == "Harbor Bookkeeping" for l in res["leads"]) == 1


def test_a_refused_key_stops_the_search_with_a_plain_message(monkeypatch):
    monkeypatch.setattr(finder.requests, "get", fake_get_with_tomtom(status=403, message="Forbidden"))
    with pytest.raises(finder.SearchError, match="TomTom refused"):
        run()


def test_google_still_wins_when_both_keys_are_set(monkeypatch):
    from fakes import fake_post_factory
    monkeypatch.setattr(finder.requests, "get", fake_get_with_tomtom())
    monkeypatch.setattr(finder.requests, "post", fake_post_factory())
    monkeypatch.setattr(finder.time, "sleep", lambda s: None)
    res = finder.find_leads(PROFILE, limit=40, google_key="g", tomtom_key="t", mx=lambda d: True, verify=VERIFY)
    assert res["source"] == "Google Maps"
    res = finder.find_leads(PROFILE, limit=40, google_key="g", tomtom_key="t", map_source="tomtom", mx=lambda d: True,
                            verify=VERIFY)
    assert res["source"] == "TomTom"
