import time

import pytest
from fastapi.testclient import TestClient

import finder
import server
from fakes import fake_get, fake_post_factory

PROFILE = {"sell": "invoice review software", "types": ["Accounting and bookkeeping firms"], "types_other": "",
           "city": "Seattle, WA", "radius": "10 miles", "deciders": ["The owner"], "signals": [],
           "avoid": ["Chains and franchises"], "do_not_contact": []}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(finder.requests, "get", fake_get)
    monkeypatch.setattr(finder.requests, "post", fake_post_factory())
    monkeypatch.setattr(finder.time, "sleep", lambda s: None)
    monkeypatch.setattr(finder, "verify_email", lambda e, **kw: {"status": "domain_ok", "detail": "ok"})
    monkeypatch.setattr(server, "GOOGLE_KEY", "test-key")
    monkeypatch.setattr(server, "CLAUDE_KEY", "")
    server._recent.clear()
    return TestClient(server.app)


def wait(c, job_id):
    for _ in range(100):
        d = c.get(f"/api/search/{job_id}").json()
        if d["state"] != "running":
            return d
        time.sleep(0.05)
    raise AssertionError("search never finished")


def test_home_page_and_status(client):
    assert "Leadline" in client.get("/").text
    s = client.get("/api/status").json()
    assert s == {**s, "google": True, "claude": False}
    assert "Law firms" in s["options"]["types"]


def test_search_runs_and_returns_dashboard_cards(client):
    d = wait(client, client.post("/api/search", json={"profile": PROFILE, "how_many": 20}).json()["job_id"])
    assert d["state"] == "done", d.get("error")
    cards = {c["business_name"]: c for c in d["result"]["leads"]}
    harbor = cards["Harbor Bookkeeping"]
    assert harbor["email"] == "maria@harborbooks.com" and harbor["tier"] in ("now", "try")
    assert harbor["contact_name"] == "Maria Lopez"
    assert {"lead_id", "business_score", "why_good", "watch_out", "tier_label", "next"} <= set(harbor)
    assert cards["Phone Only Tax"]["tier"] == "need_email"
    assert cards["Gone Accounting"]["tier"] == "skip"


def test_missing_answers_get_plain_errors(client):
    r = client.post("/api/search", json={"profile": {**PROFILE, "city": ""}})
    assert r.status_code == 400 and "city" in r.json()["detail"]


def test_adding_an_email_rescores_the_lead(client):
    job = client.post("/api/search", json={"profile": PROFILE}).json()["job_id"]
    lead = next(c for c in wait(client, job)["result"]["leads"] if c["business_name"] == "Phone Only Tax")
    card = client.post("/api/add-email", json={"job_id": job, "lead_id": lead["lead_id"], "email": "owner@phoneonlytax.com",
                                                "profile": PROFILE}).json()
    assert card["email"] == "owner@phoneonlytax.com" and card["tier"] != "need_email"


def test_searches_are_limited_per_visitor(client, monkeypatch):
    monkeypatch.setattr(server, "SEARCHES_PER_HOUR", 1)
    assert client.post("/api/search", json={"profile": PROFILE}).status_code == 200
    assert client.post("/api/search", json={"profile": PROFILE}).status_code == 429


def test_draft_without_claude_uses_the_template(client):
    out = client.post("/api/draft", json={"sender": {"company": "Flowstack"}, "lead": {"business_name": "Harbor Bookkeeping"}}).json()
    assert out["by"] == "template" and "no thanks" in out["body"]


def test_busy_free_map_gets_a_plain_message():
    msg = server.plain_error("The free map service is busy right now. Wait a minute and press Find leads again. (Errors: SSLError ...)")
    assert "Google key" in msg and "SSLError" not in msg


def test_anywhere_in_the_us_needs_no_city_with_google(client):
    d = wait(client, client.post("/api/search", json={"profile": {**PROFILE, "city": "", "radius": finder.ANYWHERE}}).json()["job_id"])
    assert d["state"] == "done", d.get("error")
    assert not any("outside the area" in c["next"] for c in d["result"]["leads"])


def test_read_business_needs_claude(client):
    r = client.post("/api/read-business", json={"text": "We are Harbor Bookkeeping."})
    assert r.status_code == 400 and "Claude key" in r.json()["detail"]


def test_read_business_fills_profile_from_text(client, monkeypatch):
    class C:
        messages = None
        def __init__(self): self.messages = self; self.prompt = ""
        def create(self, model, max_tokens, messages):
            self.prompt = messages[0]["content"]
            out = '{"company": "Harbor Bookkeeping", "sell": "monthly bookkeeping", "problem": "", "made_up": "x"}'
            return type("M", (), {"content": [type("B", (), {"type": "text", "text": out})()]})()
    c = C()
    monkeypatch.setattr(server, "CLAUDE_KEY", "k")
    monkeypatch.setattr(server, "_claude", c)
    d = client.post("/api/read-business", json={"text": "Harbor Bookkeeping does monthly bookkeeping."}).json()
    assert d["company"] == "Harbor Bookkeeping" and d["sell"] == "monthly bookkeeping"
    assert set(d) == set(server.PROFILE_FIELDS) and "information only" in c.prompt


def _upload(client, name, data: bytes):
    import base64
    return client.post("/api/extract", json={"name": name, "data": base64.b64encode(data).decode()})


def test_word_and_email_files_are_read(client):
    import io, zipfile
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("word/document.xml", "<w:document><w:body><w:p><w:r><w:t>We automate reconciliation.</w:t></w:r></w:p></w:body></w:document>")
    assert _upload(client, "about.docx", b.getvalue()).json()["text"] == "We automate reconciliation."
    eml = b"From: a@b.com\nSubject: Hello\nContent-Type: text/plain\n\nHi Dana,\n\nShort note.\n"
    d = _upload(client, "note.eml", eml).json()
    assert d["is_email"] and "Hi Dana" in d["text"]


def test_unsupported_and_empty_files_get_plain_messages(client):
    assert "Save it as a PDF" in _upload(client, "deck.pptx", b"x").json()["detail"]
    assert "any text" in _upload(client, "blank.txt", b"   ").json()["detail"]


def test_keys_can_only_be_changed_on_this_computer(client):
    assert client.post("/api/keys", json={"google": "x" * 30}).status_code == 403


def test_saving_and_removing_a_key(client, monkeypatch, tmp_path):
    monkeypatch.setattr(server, "HERE", tmp_path)
    monkeypatch.setattr(server, "LOCAL_HOSTS", server.LOCAL_HOSTS | {"testclient"})
    (tmp_path / ".env").write_text("GOOGLE_MAPS_API_KEY=\nANTHROPIC_API_KEY=\n# keep me\n")
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    assert client.post("/api/keys", json={"claude": "not-a-claude-key-at-all-123"}).status_code == 400
    s = client.post("/api/keys", json={"google": "AIza" + "x" * 30}).json()
    assert s["google"] is True and "AIza" not in str(s)
    env = (tmp_path / ".env").read_text()
    assert "GOOGLE_MAPS_API_KEY=AIza" in env and "# keep me" in env
    assert client.post("/api/keys", json={"google": ""}).json()["google"] is False
    assert "GOOGLE_MAPS_API_KEY=\n" in (tmp_path / ".env").read_text()


# ---------------------------------------------------------------- TomTom
@pytest.fixture
def tomtom_client(monkeypatch):
    from fakes import fake_get_with_tomtom
    monkeypatch.setattr(finder.requests, "get", fake_get_with_tomtom())
    monkeypatch.setattr(finder.requests, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no Google/OSM")))
    monkeypatch.setattr(finder.time, "sleep", lambda s: None)
    monkeypatch.setattr(finder, "verify_email", lambda e, **kw: {"status": "domain_ok", "detail": "ok"})
    monkeypatch.setattr(server, "GOOGLE_KEY", "")
    monkeypatch.setattr(server, "TOMTOM_KEY", "tt-key")
    monkeypatch.setattr(server, "MAP_SOURCE", "")
    monkeypatch.setattr(server, "CLAUDE_KEY", "")
    server._recent.clear()
    return TestClient(server.app)


def test_status_says_tomtom_and_hides_review_based_options(tomtom_client):
    s = tomtom_client.get("/api/status").json()
    assert s["source"] == "tomtom" and s["source_label"] == "TomTom" and s["google"] is False
    assert "no review data" in s["source_note"]
    assert s["options"]["signals"] == ["No website"]


def test_status_follows_the_keys_and_the_override(tomtom_client, monkeypatch):
    monkeypatch.setattr(server, "GOOGLE_KEY", "g")
    assert tomtom_client.get("/api/status").json()["source"] == "google"
    monkeypatch.setattr(server, "MAP_SOURCE", "tomtom")
    assert tomtom_client.get("/api/status").json()["source"] == "tomtom"
    monkeypatch.setattr(server, "MAP_SOURCE", "osm")
    assert "Free mode" in tomtom_client.get("/api/status").json()["source_note"]
    monkeypatch.setattr(server, "GOOGLE_KEY", "")
    monkeypatch.setattr(server, "TOMTOM_KEY", "")
    monkeypatch.setattr(server, "MAP_SOURCE", "")
    assert tomtom_client.get("/api/status").json()["source"] == "osm"


def test_a_search_with_tomtom_returns_dashboard_cards(tomtom_client):
    d = wait(tomtom_client, tomtom_client.post("/api/search", json={"profile": PROFILE}).json()["job_id"])
    assert d["state"] == "done", d.get("error")
    assert d["result"]["source"] == "TomTom"
    cards = {c["business_name"]: c for c in d["result"]["leads"]}
    harbor = cards["Harbor Bookkeeping"]
    assert harbor["found_on"] == "TomTom" and harbor["tier"] == "now" and harbor["email"] == "maria@harborbooks.com"
    assert harbor["google_rating"] is None and harbor["review_count"] is None
    assert cards["TaxChain Seattle"]["tier"] == "skip" and cards["Phone Only Tax"]["tier"] == "need_email"


def test_a_tomtom_problem_reaches_the_owner_in_plain_words(tomtom_client, monkeypatch):
    from fakes import fake_get_with_tomtom
    monkeypatch.setattr(finder.requests, "get", fake_get_with_tomtom(status=403, message="Forbidden"))
    d = wait(tomtom_client, tomtom_client.post("/api/search", json={"profile": PROFILE}).json()["job_id"])
    assert d["state"] == "error" and "TomTom refused" in d["error"]
