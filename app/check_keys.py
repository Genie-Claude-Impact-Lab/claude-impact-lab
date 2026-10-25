"""Check that your map and Claude keys work, before you start the app.

Run it from the app folder:   .venv/bin/python check_keys.py

It reads the keys from your .env file, tries one tiny real search per map key and one tiny Claude request, and tells
you in plain words what to fix. It never prints your keys. A TomTom check uses 1 of your 2,500 free monthly searches.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

import finder

HERE = Path(__file__).parent
SEATTLE = (47.6062, -122.3321)

GOOGLE_FIXES = [
    (("api key not valid", "api_key_invalid", "invalid api key"),
     "Google doesn't recognise this key. Copy it again from Credentials in Google Cloud Console, with no spaces or quotes."),
    (("has not been used in project", "is disabled", "service_disabled", "not enabled"),
     "Places API (New) isn't turned on. In Google Cloud Console open APIs & Services, then Library, search for "
     "“Places API (New)” and press Enable."),
    (("billing", "billing_disabled"),
     "Billing isn't switched on for this Google project. Open Billing in Google Cloud Console and link an account."),
    (("requests to this api", "api_key_service_blocked", "api_target_blocked"),
     "The key is restricted to other APIs. Open the key, go to API restrictions, and tick “Places API (New)”."),
    (("requests from referer", "requests from ip", "referer", "referrer", "api_key_http_referrer_blocked",
      "api_key_ip_address_blocked"),
     "The key has an application restriction that blocks this computer. Set Application restrictions to “None”."),
    (("quota", "rate limit", "resource_exhausted", "exceeded"),
     "You've hit a usage limit. If you set a daily cap, raise it or wait until tomorrow."),
]


def explain_google_error(message: str) -> str:
    low = (message or "").lower()
    for needles, fix in GOOGLE_FIXES:
        if any(n in low for n in needles):
            return fix
    return "Read Google's message above. The Google key section of the README lists the usual causes."


def explain_tomtom_error(message: str) -> str:
    low = (message or "").lower()
    if "volume" in low or "limit" in low or "quota" in low:
        return ("This month's free TomTom searches may be used up (the free allowance is 2,500 a month and resets each "
                "month). Check your usage on the TomTom dashboard.")
    if "referer" in low or "referrer" in low:
        return "The key is restricted to certain websites. In the TomTom dashboard, remove the website restriction."
    return ("TomTom doesn't accept this key for searching. Copy it again from the TomTom dashboard with no spaces or "
            "quotes. If you chose products when you made the key, make sure Search API is included.")


def _split(text: str, marker: str) -> str:
    return text.split(marker, 1)[-1].strip() if marker in text else text


def check_tomtom(key: str) -> tuple[bool, str]:
    """One real search through the app's own code, so a pass means the app will work too."""
    try:
        found = finder.tomtom_search("coffee shop", key, SEATTLE, 5, 3)
    except finder.SearchError as e:
        text = str(e)
        said = _split(text, "TomTom said:")
        return False, f"{text}\n    Fix: {explain_tomtom_error(said)}"
    except Exception as e:
        return False, f"Couldn't reach TomTom ({type(e).__name__}). Check your internet connection and try again."
    if not found:
        return False, "TomTom answered but found nothing. The key works, so try again in a moment."
    first = found[0]
    return True, (f"Found {len(found)} places, for example “{first['business_name']}”. "
                  f"Website: {'yes' if first.get('website') else 'not listed'}. "
                  f"Phone: {'yes' if first.get('phone') else 'not listed'}.")


def check_google(key: str) -> tuple[bool, str]:
    try:
        found = finder.google_search("coffee shop in Seattle, WA", key, SEATTLE, 5, 3)
    except finder.SearchError as e:
        said = _split(str(e), "Google said:")
        return False, f"{said}\n    Fix: {explain_google_error(said)}"
    except Exception as e:
        return False, f"Couldn't reach Google ({type(e).__name__}). Check your internet connection and try again."
    if not found:
        return False, "Google answered but found nothing. The key works, so try again in a moment."
    return True, f"Found {len(found)} places, for example “{found[0]['business_name']}”."


def check_claude(key: str, model: str) -> tuple[bool, str]:
    try:
        import anthropic
        anthropic.Anthropic(api_key=key).messages.create(model=model, max_tokens=5,
                                                         messages=[{"role": "user", "content": "Reply with OK."}])
    except Exception as e:
        name = type(e).__name__
        if "Authentication" in name or "PermissionDenied" in name:
            return False, "Claude rejected this key.\n    Fix: create a new key in the Claude console (API keys, Create key) " \
                          "and paste the whole thing into .env."
        if "NotFound" in name:
            return False, f"Claude doesn't know the model “{model}”.\n    Fix: remove CLAUDE_MODEL from .env, or set a model your account can use."
        if "RateLimit" in name or "Overloaded" in name:
            return False, "Claude is busy or you've hit a limit. The key looks fine. Try again in a minute."
        if "BadRequest" in name and "credit" in str(e).lower():
            return False, "Your Claude account is out of credit.\n    Fix: add credit in the Claude console under Billing."
        return False, f"Couldn't reach Claude ({name}). Check your internet connection and try again."
    return True, f"Claude answered using {model}."


def _report(title: str, key: str, runner, missing: str) -> bool:
    """Prints one section. Returns True if it failed."""
    print(title)
    if not key:
        print(f"  – not set. {missing}")
        return False
    ok, msg = runner(key)
    print(f"  {'✓' if ok else '✗'} {msg}")
    return not ok


def main() -> int:
    load_dotenv(HERE / ".env")
    env = lambda k: os.environ.get(k, "").strip()
    tomtom, google, claude = env("TOMTOM_API_KEY"), env("GOOGLE_MAPS_API_KEY"), env("ANTHROPIC_API_KEY")
    model = env("CLAUDE_MODEL") or "claude-sonnet-5-5"
    if not (HERE / ".env").exists():
        print("There's no .env file in this folder yet.\n"
              "Run:  cp .env.example .env   then open .env and paste your keys after the = signs.\n")
    failed = False
    failed |= _report("TomTom key", tomtom, check_tomtom, "That's fine: the app can use Google or the free map instead.")
    failed |= _report("Google Maps key", google, check_google, "That's fine if you're using TomTom.")
    failed |= _report("Claude key", claude, lambda k: check_claude(k, model),
                      "Emails will use a plain template and you'll fill in the details yourself.")
    src = finder.pick_source(google, tomtom, env("MAP_SOURCE"))
    print(f"\nThe app will search: {finder.SOURCE_LABEL[src]}.")
    if failed:
        print("Fix the ✗ above, then run this again.")
    elif tomtom or google or claude:
        print("All set. Start the app with:  .venv/bin/python run.py")
    else:
        print("No keys yet. The app still works in free mode. Add keys to .env when you have them.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
