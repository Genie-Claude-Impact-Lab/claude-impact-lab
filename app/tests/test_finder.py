import pytest
import finder
from fakes import fake_get, fake_post_factory, FakeClaude, PLACES, place

PROFILE = {"sell": "invoice review software", "types": ["Accounting and bookkeeping firms"], "types_other": "",
           "city": "Seattle, WA", "radius": "10 miles", "deciders": ["The owner"], "signals": ["Few reviews"],
           "avoid": ["Chains and franchises"], "do_not_contact": []}

@pytest.fixture
def offline(monkeypatch):
    post = fake_post_factory()
    monkeypatch.setattr(finder.requests, "get", fake_get)
    monkeypatch.setattr(finder.requests, "post", post)
    monkeypatch.setattr(finder.time, "sleep", lambda s: None)
    return post

def run(claude=None, profile=PROFILE, **kw):
    return finder.find_leads(profile, limit=40, google_key="test-key", claude_client=claude,
                             mx=lambda d: True, **kw)

def lead(res, name):
    return next(l for l in res["leads"] if l["business_name"] == name)

# ---------- email extraction from real-looking HTML
def test_extracts_mailto_plain_and_cloudflare_emails():
    html = ('<a href="mailto:Jane@Shop.com?subject=hi">x</a> sales@shop.com '
            '<span data-cfemail="CFCFA7AAA3A3A0"></span> logo@2x.png user@example.com')
    assert finder.emails_in_html(html) == ["jane@shop.com", "sales@shop.com"] + [finder.decode_cfemail("CFCFA7AAA3A3A0")] \
        or set(finder.emails_in_html(html)) >= {"jane@shop.com", "sales@shop.com"}
    assert "user@example.com" not in finder.emails_in_html(html)
    assert not any(e.endswith(".png") for e in finder.emails_in_html(html))

def test_cloudflare_decoding():
    # key 0xCF; encodes "hello" -> we only check it round-trips to letters
    assert finder.decode_cfemail("CFA7AAA3A3A0") == "hello"

def test_prefers_personal_email_on_company_domain():
    emails = ["info@harborbooks.com", "maria@harborbooks.com", "harbor@gmail.com", "x@other.com"]
    assert finder.best_email(emails, "https://www.harborbooks.com") == "maria@harborbooks.com"

def test_finds_contact_and_about_links_on_same_site_only():
    page = '<a href="/contact">c</a><a href="https://facebook.com/about">f</a><a href="/about-us">a</a>'
    assert finder.useful_links(page, "https://harborbooks.com") == ["https://harborbooks.com/contact", "https://harborbooks.com/about-us"]

def test_owner_name_found_without_ai():
    assert finder.owner_from_text("Maria Lopez, Owner, founded the firm.") == {"owner_name": "Maria Lopez", "owner_title": "Owner"}
    assert finder.owner_from_text("Founder: James O’Neil".replace("’", "")) .get("owner_title") in (None, "Founder")
    assert finder.owner_from_text("Meet Sam Park, our founder.")["owner_name"] == "Sam Park"
    assert finder.owner_from_text("We are a friendly team.") == {}
    # real-world format seen on accounting firm sites (names changed)
    team = "Our Team: Pat Rivera, CPA Managing Member Lee Wong, CPA, MBA Partner Ana Diaz Office Manager"
    assert finder.owner_from_text(team) == {"owner_name": "Pat Rivera", "owner_title": "Managing Member"}

def test_google_results_are_parsed():
    l = finder.parse_google(place("9", "X", website="https://x.com", review_days=5))
    assert l["business_name"] == "X" and l["status"] == "open" and l["review_count"] == 40
    assert finder.days_since(l["last_review_date"]) <= 6

# ---------- the whole pipeline (offline)
def test_full_run_ranks_real_businesses(offline):
    res = run(FakeClaude())
    assert res["source"] == "Google Maps"
    harbor = lead(res, "Harbor Bookkeeping")
    assert harbor["email"] == "maria@harborbooks.com"
    assert harbor["contact_name"] == "Maria Lopez"
    assert harbor["tier"] == "now"
    assert res["leads"][0]["business_name"] == "Harbor Bookkeeping"

def test_search_is_sent_to_google_with_key_and_location(offline):
    run()
    call = offline.calls[0]
    assert call["headers"]["X-Goog-Api-Key"] == "test-key"
    assert "reviews" in call["headers"]["X-Goog-FieldMask"]
    assert call["json"]["textQuery"] == "accounting firm in Seattle, WA"
    assert "locationBias" in call["json"]

def test_closed_chains_and_far_away_are_skipped(offline):
    res = run()
    assert lead(res, "Gone Accounting")["tier"] == "skip"
    assert all(l["tier"] == "skip" for l in res["leads"] if l["business_name"] == "TaxChain")
    tac = lead(res, "Tacoma Ledger")
    assert tac["tier"] == "skip" and "miles away" in tac["next"]

def test_business_with_no_email_goes_to_need_an_email(offline):
    l = lead(run(), "Phone Only Tax")
    assert l["tier"] == "need_email"
    assert "(206) 555-0199" in l["next"]
    assert "has only 8 reviews" in " ".join(l["why"])

def test_cloudflare_protected_email_is_found(offline):
    assert lead(run(), "Elliott CPA Group")["all_emails"][0] in ("hello@elliottcpa.com", "office@elliottcpa.com")

def test_made_up_owner_name_is_rejected(offline):
    l = lead(run(FakeClaude()), "Fake Name Books")
    assert l.get("contact_name", "") == ""
    assert any("Jordan Smith" in c for c in l["check"])

def test_email_whose_domain_cannot_receive_mail_is_dropped(offline):
    res = finder.find_leads(PROFILE, limit=40, google_key="k", mx=lambda d: d != "harborbooks.com")
    l = lead(res, "Harbor Bookkeeping")
    assert l["email"] == ""
    assert any("isn’t set up to receive email" in c for c in l["check"])

def test_do_not_contact_list_is_respected(offline):
    p = {**PROFILE, "do_not_contact": ["harbor bookkeeping"]}
    res = run(profile=p)
    l = lead(res, "Harbor Bookkeeping")
    assert l["tier"] == "skip" and "do-not-contact" in l["next"]

def test_bad_google_key_gives_plain_message(monkeypatch):
    monkeypatch.setattr(finder.requests, "get", fake_get)
    monkeypatch.setattr(finder.requests, "post", fake_post_factory(status=403))
    with pytest.raises(finder.SearchError, match="Places API"):
        run()

def test_missing_answers_give_plain_messages(offline):
    with pytest.raises(finder.SearchError, match="kind of business"):
        run(profile={**PROFILE, "types": []})
    with pytest.raises(finder.SearchError, match="city"):
        run(profile={**PROFILE, "city": ""})

def test_free_mode_uses_openstreetmap(monkeypatch):
    monkeypatch.setattr(finder.requests, "get", fake_get)
    def post(url, data=None, **kw):
        from fakes import Resp
        assert "office~" in data["data"]
        return Resp(200, data={"elements": [{"type": "node", "id": 1, "lat": 47.61, "lon": -122.33,
            "tags": {"name": "Harbor Bookkeeping", "office": "accountant", "website": "https://harborbooks.com", "addr:city": "Seattle"}}]})
    monkeypatch.setattr(finder.requests, "post", post)
    res = finder.find_leads(PROFILE, limit=10, google_key="", mx=lambda d: True)
    assert res["source"] == "OpenStreetMap"
    assert lead(res, "Harbor Bookkeeping")["email"] == "maria@harborbooks.com"

def test_one_broken_website_does_not_stop_the_run(offline):
    def visit(url):
        if "elliott" in url:
            raise RuntimeError("boom")
        return finder.visit_website(url)
    res = run(visit=visit)
    assert lead(res, "Elliott CPA Group")["tier"] == "need_email"
    assert lead(res, "Harbor Bookkeeping")["tier"] in ("now", "try")

def test_first_email_has_opt_out_line():
    l = {"business_name": "Harbor Bookkeeping", "contact_name": "Maria Lopez"}
    m = finder.template_email(PROFILE, l)
    assert m["body"].startswith("Hi Maria,") and "no thanks" in m["body"] and "invoice review software" in m["body"]
    m2 = finder.claude_email(FakeClaude(), "m", PROFILE, l)
    assert "no thanks" in m2["body"]

def test_csv_rows_have_plain_priority_labels(offline):
    rows = finder.to_rows(run()["leads"])
    assert rows[0]["priority"] == "Contact now"
    assert set(rows[0]) == set(finder.CSV_COLUMNS)

# ---------- free mode (no Google key)
def test_free_map_asks_all_servers_at_once_and_uses_a_good_answer():
    from fakes import Resp
    tried = []
    def post(url, **kw):
        tried.append(url)
        if len(tried) < 3:
            return Resp(502, "busy")
        return Resp(200, data={"elements": [{"type": "node", "id": 5, "lat": 47.6, "lon": -122.3, "tags": {"name": "A"}}]})
    out = finder.osm_search(['office~"^(accountant)$"'], (47.6, -122.3), 10, 20, post=post, pause=lambda s: None)
    assert [l["business_name"] for l in out] == ["A"]
    assert len(set(tried)) == len(tried) <= len(finder.OVERPASS)   # all asked at once, each only once

def test_free_map_gives_plain_message_when_all_servers_are_busy():
    from fakes import Resp
    with pytest.raises(finder.SearchError, match="busy right now"):
        finder.osm_search(['office~"x"'], (47.6, -122.3), 10, 20, post=lambda u, **k: Resp(504, ""), pause=lambda s: None)

def test_free_mode_scores_are_scaled_so_good_leads_can_be_contact_now():
    lead_ = {"business_name": "Harbor", "email": "maria@harborbooks.com", "website": "https://harborbooks.com",
             "phone": "1", "contact_name": "Maria Lopez", "contact_title": "Owner", "found_on": "OpenStreetMap"}
    s = finder.score(lead_, PROFILE)
    assert s["tier"] == "now" and s["score"] == 81      # 65 of a possible 80

def test_name_filter_for_something_else_is_safe():
    assert finder.osm_name_filter('dog "groomers"; drop') == '"name"~"dog groomers drop",i'

def test_business_whose_website_is_for_sale_is_skipped(offline):
    l = lead(run(), "Old Domain CPA")
    assert l["tier"] == "skip" and "up for sale" in l["next"]
    assert finder.is_parked("https://forsale.godaddy.com/forsale/x.com", "")

def test_domain_sale_emails_are_never_used():
    assert finder.emails_in_html("service@afternic.com partnerseller@afternic.com") == []

def test_slow_websites_do_not_hold_up_the_results(offline):
    import time as _t
    def visit(url):
        if "elliott" in url:
            import threading
            threading.Event().wait(3)   # time.sleep is switched off by the offline fixture
        return finder.visit_website(url)
    import finder as f
    start = _t.time()
    items = list(f._parallel(visit, ["https://harborbooks.com", "https://elliottcpa.com"], 4, deadline=1))
    assert _t.time() - start < 2.5
    assert any(isinstance(r, TimeoutError) for _, r in items)


# ---------- smarter features
def test_claude_turns_a_sentence_into_search_answers():
    d = finder.claude_understand(FakeClaude(), "m", "I sell invoice review software to accountants in Seattle")
    assert d["types"] == ["Accounting and bookkeeping firms"]          # made-up choices are dropped
    assert d["city"] == "Seattle, WA" and d["radius"] == "25 miles"

def test_claude_fit_and_hook_shape_the_ranking(offline):
    res = run(FakeClaude())
    harbor = lead(res, "Harbor Bookkeeping")
    assert harbor["fit"] == 88 and "invoices" in harbor["hook"]
    assert any("strong fit" in w for w in harbor["why"])
    elliott = lead(res, "Elliott CPA Group")            # Claude says fit 20
    assert elliott["tier"] == "later" and "Probably not your customer" in elliott["next"]

def test_progress_log_tells_the_story(offline):
    lines = []
    run(FakeClaude(), log=lines.append)
    text = " ".join(lines)
    assert "Found 9 businesses on Google Maps" in text
    assert "Visiting" in text and "Claude is reading" in text

def test_owner_can_add_an_email_found_by_phone(offline):
    res = run()
    phone_only = lead(res, "Phone Only Tax")
    assert phone_only["tier"] == "need_email"
    updated = finder.with_manual_email(phone_only, "dana@phoneonlytax.com", PROFILE)
    assert updated["email"] == "dana@phoneonlytax.com" and updated["tier"] in ("now", "try", "later")
    assert updated["why"][0] == "You added this email yourself."
    assert finder.with_manual_email(phone_only, "not an email", PROFILE)["tier"] == "need_email"


# ---------- email verification
def test_verify_rejects_bad_format_and_throwaway_domains():
    assert finder.verify_email("not-an-email")["status"] == "invalid"
    assert finder.verify_email("a@mailinator.com", has_mx_fn=lambda d: True)["status"] == "invalid"

def test_verify_domain_without_mail_servers_is_invalid():
    assert finder.verify_email("a@nomail.com", hosts_fn=lambda d: [])["status"] == "invalid"

def test_verify_uses_mail_server_answer(monkeypatch):
    monkeypatch.setattr(finder, "SMTP_CHECK", True)
    hosts = lambda d: ["mx.example.net"]
    assert finder.verify_email("maria@shop.com", hosts_fn=hosts, probe=lambda e, h: (True, False))["status"] == "valid"
    assert finder.verify_email("nobody@shop.com", hosts_fn=hosts, probe=lambda e, h: (False, False))["status"] == "invalid"
    assert finder.verify_email("maria@shop.com", hosts_fn=hosts, probe=lambda e, h: (True, True))["status"] == "accepts_all"
    assert finder.verify_email("maria@shop.com", hosts_fn=hosts, probe=lambda e, h: (None, None))["status"] == "domain_ok"
    assert finder.verify_email("maria@shop.com", hosts_fn=lambda d: None)["status"] == "unknown"

def test_pipeline_drops_mailboxes_that_do_not_exist_and_uses_the_next(offline):
    def verify(e):
        return {"status": "invalid", "detail": "Their mail server says this mailbox doesn’t exist."} if e.startswith("maria@") \
            else {"status": "valid", "detail": "ok"}
    res = finder.find_leads(PROFILE, limit=40, google_key="k", verify=verify)
    l = lead(res, "Harbor Bookkeeping")
    assert l["email"] == "info@harborbooks.com" and l["email_status"] == "valid"
    assert any("Left out maria@harborbooks.com" in c for c in l["check"])
    assert any("Mailbox confirmed" in w for w in l["why"])

def test_added_email_is_verified(offline):
    phone_only = lead(run(), "Phone Only Tax")
    bad = finder.with_manual_email(phone_only, "x@nowhere.com", PROFILE, verify=lambda e: {"status": "invalid", "detail": "no"})
    assert bad["email"] == "" and bad["tier"] == "need_email"
    good = finder.with_manual_email(phone_only, "dana@phoneonlytax.com", PROFILE, verify=lambda e: {"status": "valid", "detail": "ok"})
    assert good["email_status"] == "valid"


def test_custom_roles_count_as_decision_makers():
    lead = {"email": "pat@x.com", "contact_name": "Pat Lee", "contact_title": "Head of Operations", "website": "https://x.com",
            "found_on": "Google Maps"}
    plain = finder.score(lead, {"deciders": ["The owner"]})
    custom = finder.score(lead, {"deciders": ["The owner"], "deciders_other": ["Head of Operations"]})
    assert custom["score"] == plain["score"] + 10


def test_fit_check_uses_the_whole_profile():
    c = FakeClaude()
    finder.claude_read_site(c, "m", {"sell": "invoice software", "problem": "month-end takes days",
                                     "ideal_customer": "small CPA firms"}, "Harbor", "Maria Lopez runs Harbor.")
    assert "month-end takes days" in c.prompts[0] and "small CPA firms" in c.prompts[0]


def test_anywhere_without_google_searches_widely_around_the_city(offline, monkeypatch):
    seen = {}
    monkeypatch.setattr(finder, "osm_search", lambda f, c, r, l, **kw: seen.setdefault("r", r) and [])
    finder.find_leads({**PROFILE, "radius": finder.ANYWHERE}, google_key="", mx=lambda d: True)
    assert seen["r"] == finder.FREE_MAP_WIDEST
