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
