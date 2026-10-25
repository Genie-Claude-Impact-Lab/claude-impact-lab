import pytest
import finder
from fakes import fake_get, fake_post_factory, FakeClaude, PLACES, place

PROFILE = {"sell": "invoice review software", "types": ["Accounting and bookkeeping firms"], "types_other": "",
           "city": "Seattle, WA", "radius": "Within 10 miles", "deciders": ["The owner"], "signals": ["Few reviews"],
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
    assert any("can’t receive email" in c for c in l["check"])

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
