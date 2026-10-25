"""Clicks through the real Streamlit page with fake data."""
import os
from streamlit.testing.v1 import AppTest
import finder
from fakes import fake_get, fake_post_factory, FakeClaude

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


def open_app(monkeypatch, google=True, claude=False):
    monkeypatch.setattr(finder.requests, "get", fake_get)
    monkeypatch.setattr(finder.requests, "post", fake_post_factory())
    monkeypatch.setattr(finder.time, "sleep", lambda s: None)
    real = finder.find_leads
    monkeypatch.setattr(finder, "find_leads", lambda *a, **k: real(*a, **{**k, "mx": lambda d: True}))
    for name, on in (("GOOGLE_MAPS_API_KEY", google), ("ANTHROPIC_API_KEY", claude)):
        if on:
            monkeypatch.setenv(name, "test-key")
        else:
            monkeypatch.delenv(name, raising=False)
    if claude:
        import anthropic
        fake = FakeClaude()
        monkeypatch.setattr(anthropic, "Anthropic", lambda api_key=None: fake)
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    return at


def click(at, label):
    next(b for b in at.button if b.label == label).click()
    at.run()


def fill(at, sell="invoice review software", types=("Accounting and bookkeeping firms",), city="Seattle, WA"):
    at.text_input(key="sell").set_value(sell)
    at.session_state["types"] = list(types)
    at.text_input(key="city").set_value(city)


def test_page_loads(monkeypatch):
    at = open_app(monkeypatch)
    assert not at.exception
    assert any("Find your next customers." in m.value for m in at.markdown)


def test_missing_answers_show_friendly_errors(monkeypatch):
    at = open_app(monkeypatch)
    click(at, "Find leads")
    assert "what you sell" in at.error[0].value
    fill(at, types=())
    click(at, "Find leads")
    assert "kind of business" in at.error[0].value


def test_example_then_find_shows_results_map_and_table(monkeypatch):
    at = open_app(monkeypatch)
    click(at, "Try an example")
    assert at.text_input(key="city").value == "Seattle, WA"
    click(at, "Find leads")
    assert not at.exception, at.exception
    page = " ".join(m.value for m in at.markdown)
    assert "Your leads" in page
    for label in ["Contact now", "Worth a try", "Need an email", "Set aside"]:
        assert label in page
    assert "Mailbox confirmed" in page or "Domain accepts mail" in page
    assert len(at.dataframe) == 1


def test_smart_setup_from_one_sentence(monkeypatch):
    at = open_app(monkeypatch, claude=True)
    at.text_area(key="desc").set_value("I sell invoice review software to accountants in Seattle")
    click(at, "Fill in the details for me")
    assert not at.exception, at.exception
    assert at.session_state["types"] == ["Accounting and bookkeeping firms"]
    assert at.text_input(key="city").value == "Seattle, WA"
    assert any("Check the details" in s.value for s in at.success) or at.success


def test_with_claude_best_lead_shows_hook_and_email_draft(monkeypatch):
    at = open_app(monkeypatch, claude=True)
    click(at, "Try an example")
    click(at, "Find leads")
    assert not at.exception, at.exception
    assert any("review lots of invoices" in m.value for m in at.markdown)
    click(at, "Write my first email")
    assert not at.exception, at.exception
    draft = [c.value for c in at.code if c.value.startswith("To:")]
    assert draft and "maria@harborbooks.com" in draft[0] and "no thanks" in draft[0]


def test_adding_an_email_moves_a_lead_up(monkeypatch):
    import re
    monkeypatch.setattr(finder, "verify_email", lambda e, **k: {"status": "valid", "detail": "ok"})
    at = open_app(monkeypatch)
    click(at, "Try an example")
    click(at, "Find leads")
    count = lambda: int(re.search(r"<b>(\d+)</b><span>Need an email", " ".join(m.value for m in at.markdown)).group(1))
    before = count()
    box = next(t for t in at.text_input if t.key.startswith("add-"))
    box.set_value("dana@phoneonlytax.com").run()
    assert count() == before - 1
