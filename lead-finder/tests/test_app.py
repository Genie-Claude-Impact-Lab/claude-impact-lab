"""Clicks through the real Streamlit page with fake data."""
import os
from streamlit.testing.v1 import AppTest
import finder
from fakes import fake_get, fake_post_factory, FakeClaude

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")

def open_app(monkeypatch, google=True):
    monkeypatch.setattr(finder.requests, "get", fake_get)
    monkeypatch.setattr(finder.requests, "post", fake_post_factory())
    monkeypatch.setattr(finder.time, "sleep", lambda s: None)
    monkeypatch.setattr(finder, "has_mx", lambda d: True)
    real = finder.find_leads
    monkeypatch.setattr(finder, "find_leads", lambda *a, **k: real(*a, **{**k, "mx": lambda d: True}))
    if google:
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    else:
        monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    return at

def fill(at, sell="invoice review software", types=("Accounting and bookkeeping firms",), city="Seattle, WA"):
    at.text_input(key="sell").set_value(sell)
    at.session_state["types"] = list(types)
    at.text_input(key="city").set_value(city)

def submit(at):
    next(b for b in at.button if b.label == "Find leads").click()
    at.run()

def test_page_loads_with_questions(monkeypatch):
    at = open_app(monkeypatch)
    assert not at.exception
    assert at.title[0].value == "Find businesses to sell to"
    assert at.text_input(key="sell").label.startswith("1. What do you sell")

def test_free_mode_notice_without_google_key(monkeypatch):
    at = open_app(monkeypatch, google=False)
    assert any("free mode" in i.value.lower() for i in at.info)

def test_missing_answers_show_friendly_errors(monkeypatch):
    at = open_app(monkeypatch)
    submit(at)
    assert "what you sell" in at.error[0].value
    fill(at, types=())
    submit(at)
    assert "kind of business" in at.error[0].value

def test_find_leads_shows_ranked_results_and_download(monkeypatch):
    at = open_app(monkeypatch)
    fill(at)
    submit(at)
    assert not at.exception, at.exception
    assert at.header[0].value == "Your leads"
    assert [m.label for m in at.metric][:2] == ["Contact now", "Worth a try"]
    assert at.metric[0].value == "1"
    names = [s.value for s in at.subheader]
    assert names[0] == "Harbor Bookkeeping"
    assert any("Email" in m.value and "maria@harborbooks.com" in m.value for m in at.markdown)

def test_write_first_email_shows_copyable_draft(monkeypatch):
    at = open_app(monkeypatch)
    fill(at)
    submit(at)
    next(b for b in at.button if b.label == "Write my first email").click()
    at.run()
    assert not at.exception
    assert "To: maria@harborbooks.com" in at.code[0].value
    assert "no thanks" in at.code[0].value
