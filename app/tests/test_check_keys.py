"""The key checker explains problems in plain words. All offline."""
import check_keys
import finder
from fakes import Resp, PLACES, fake_get_with_tomtom


def google_says(monkeypatch, status, message="", places=None):
    def post(url, json=None, headers=None, **kw):
        if status == 200:
            return Resp(200, data={"places": PLACES if places is None else places})
        return Resp(status, data={"error": {"message": message}})
    monkeypatch.setattr(finder.requests, "post", post)


def clear_keys(monkeypatch):
    for k in ("TOMTOM_API_KEY", "GOOGLE_MAPS_API_KEY", "ANTHROPIC_API_KEY", "MAP_SOURCE"):
        monkeypatch.delenv(k, raising=False)


# ---------- TomTom
def test_working_tomtom_key_passes(monkeypatch):
    monkeypatch.setattr(finder.requests, "get", fake_get_with_tomtom())
    ok, msg = check_keys.check_tomtom("tt-key")
    assert ok and "Harbor Bookkeeping" in msg and "Website: yes" in msg


def test_rejected_tomtom_key_gets_a_plain_fix(monkeypatch):
    monkeypatch.setattr(finder.requests, "get", fake_get_with_tomtom(status=403, message="Forbidden"))
    ok, msg = check_keys.check_tomtom("bad")
    assert not ok and "Fix:" in msg and "copy it again" in msg.lower()


def test_used_up_tomtom_allowance_is_explained(monkeypatch):
    monkeypatch.setattr(finder.requests, "get", fake_get_with_tomtom(status=403, message="Rate or volume limit exceeded"))
    ok, msg = check_keys.check_tomtom("tt")
    assert not ok and "2,500" in msg and "used up" in msg


def test_tomtom_empty_answer_is_not_blamed_on_the_key(monkeypatch):
    monkeypatch.setattr(finder.requests, "get", fake_get_with_tomtom(results=[]))
    ok, msg = check_keys.check_tomtom("tt")
    assert not ok and "key works" in msg


def test_tomtom_network_failure_is_explained(monkeypatch):
    import requests
    def down(*a, **k):
        raise requests.ConnectionError("down")
    monkeypatch.setattr(finder.requests, "get", down)
    ok, msg = check_keys.check_tomtom("tt")
    assert not ok and "internet" in msg


# ---------- Google
def test_working_google_key_passes(monkeypatch):
    google_says(monkeypatch, 200)
    monkeypatch.setattr(finder.requests, "get", fake_get_with_tomtom())
    ok, msg = check_keys.check_google("AIza-test")
    assert ok and "Harbor Bookkeeping" in msg


def test_each_common_google_problem_gets_a_plain_fix(monkeypatch):
    cases = {
        "API key not valid. Please pass a valid API key.": "copy it again",
        "Places API (New) has not been used in project 123 before or it is disabled.": "Places API (New)",
        "This API method requires billing to be enabled.": "Billing",
        "Requests to this API places.googleapis.com method google.maps.places.v1.Places.SearchText are blocked.": "API restrictions",
        "Requests from referer <empty> are blocked.": "Application restrictions",
        "Requests from IP address 203.0.113.9 are blocked.": "Application restrictions",
    }
    for said, expect in cases.items():
        google_says(monkeypatch, 403, said)
        ok, msg = check_keys.check_google("AIza-test")
        assert not ok and expect.lower() in msg.lower(), (said, msg)


# ---------- the whole report
def test_main_never_prints_keys_and_says_which_map_is_used(monkeypatch, capsys):
    clear_keys(monkeypatch)
    monkeypatch.setattr(finder.requests, "get", fake_get_with_tomtom())
    monkeypatch.setenv("TOMTOM_API_KEY", "SECRETTOMTOM123")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-SECRET456")
    monkeypatch.setattr(check_keys, "check_claude", lambda k, m: (True, f"Claude answered using {m}."))
    assert check_keys.main() == 0
    out = capsys.readouterr().out
    assert "SECRET" not in out and "All set" in out and "The app will search: TomTom." in out


def test_main_fails_with_a_clear_next_step(monkeypatch, capsys):
    clear_keys(monkeypatch)
    monkeypatch.setattr(finder.requests, "get", fake_get_with_tomtom(status=403, message="Forbidden"))
    monkeypatch.setenv("TOMTOM_API_KEY", "bad")
    assert check_keys.main() == 1
    assert "Fix the" in capsys.readouterr().out


def test_main_with_no_keys_says_free_mode_is_fine(monkeypatch, capsys):
    clear_keys(monkeypatch)
    assert check_keys.main() == 0
    out = capsys.readouterr().out
    assert "free mode" in out.lower() and "OpenStreetMap" in out
