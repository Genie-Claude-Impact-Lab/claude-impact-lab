"""Lead Finder web server: the website plus a small API around finder.py and emails.py.

Run it with `python run.py` (see README). Keys come from a .env file next to this one, never from the code.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import emails
import finder

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")

GOOGLE_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
TOMTOM_KEY = os.environ.get("TOMTOM_API_KEY", "").strip()
MAP_SOURCE = os.environ.get("MAP_SOURCE", "").strip().lower()      # optional: google, tomtom or osm
SOURCE_NOTES = {
    "google": "Searching Google Maps.",
    "tomtom": "Searching TomTom maps. It has no review data, so ranking uses emails, names, websites and phone numbers.",
    "osm": "Free mode: searching OpenStreetMap, a free public map, which finds fewer businesses. "
           "Add a TomTom or Google key for fuller results.",
}
CLAUDE_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "").strip() or "claude-sonnet-5-5"
SEARCHES_PER_HOUR = int(os.environ.get("SEARCHES_PER_HOUR", "20"))

app = FastAPI(title="Lead Finder")
_claude = None
JOBS: dict = {}          # job id -> progress, log, result and the raw leads (for re-scoring)
_recent: dict = {}       # visitor -> times of recent searches


def source() -> str:
    """Which map this server searches, worked out from the keys it has right now."""
    return finder.pick_source(GOOGLE_KEY, TOMTOM_KEY, MAP_SOURCE)


def claude():
    global _claude
    if CLAUDE_KEY and _claude is None:
        import anthropic
        _claude = anthropic.Anthropic(api_key=CLAUDE_KEY)
    return _claude


def to_card(l: dict) -> dict:
    """One finder lead in the shape the dashboard uses."""
    good = [w for w in l.get("why", []) if not w.startswith(("No ", "Only a shared", "Uses a free", "You have a name"))]
    watch = list(l.get("check", [])) + [w for w in l.get("why", []) if w.startswith(("Only a shared", "You have a name"))]
    site = l.get("site") or {}
    return {
        "lead_id": l["id"], "business_name": l["business_name"], "category": l.get("industry") or "Business",
        "address": l.get("address", ""), "website": l.get("website", ""), "phone": l.get("phone", ""),
        "contact_name": l.get("contact_name", ""), "contact_title": l.get("contact_title", ""),
        "email": l.get("email", ""), "email_status": l.get("email_status", ""), "email_detail": l.get("email_detail", ""),
        "business_score": l.get("score", 0), "tier": l["tier"], "tier_label": finder.TIER_LABEL[l["tier"]],
        "next": l.get("next", ""), "google_rating": l.get("rating"), "review_count": l.get("review_count"),
        "last_review_date": l.get("last_review_date", ""), "summary": l.get("what_they_do", ""), "hook": l.get("hook", ""),
        "fit": l.get("fit"), "why_good": " | ".join(good), "watch_out": " | ".join(watch),
        "improve": l.get("improve", []), "pages": site.get("pages", []), "maps_url": l.get("maps_url", ""),
        "found_on": l.get("found_on", ""), "distance_mi": round(l["distance_mi"], 1) if l.get("distance_mi") else None,
    }


def _visitor(request: Request) -> str:
    return request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "?")


@app.get("/api/status")
def status():
    src = source()
    return {"google": src == "google", "source": src, "source_label": finder.SOURCE_LABEL[src],
            "source_note": SOURCE_NOTES[src], "claude": bool(CLAUDE_KEY),
            "options": {"types": list(finder.TYPES), "radius": list(finder.RADIUS_MILES),
                        "deciders": list(finder.DECIDER_WORDS),
                        "signals": finder.SIGNALS if src == "google" else ["No website"]}}


@app.post("/api/understand")
def understand(body: dict):
    text = (body.get("description") or "").strip()
    if not text:
        raise HTTPException(400, "Write a sentence about what you sell and who buys it first.")
    if not claude():
        raise HTTPException(400, "This needs a Claude key. Fill in the details below yourself.")
    try:
        return finder.claude_understand(claude(), CLAUDE_MODEL, text)
    except Exception:
        raise HTTPException(502, "Claude couldn't read that just now. Fill in the details below yourself.")


def _run(job_id: str, profile: dict, how_many: int):
    job = JOBS[job_id]

    def progress(msg, frac):
        job["message"], job["progress"] = msg, round(min(1.0, frac), 3)

    try:
        res = finder.find_leads(profile, limit=how_many, google_key=GOOGLE_KEY, tomtom_key=TOMTOM_KEY,
                                map_source=MAP_SOURCE, claude_client=claude(), claude_model=CLAUDE_MODEL,
                                progress=progress, log=lambda t: job["log"].append(t))
        job["raw"] = {l["id"]: l for l in res["leads"]}
        job["result"] = {"source": res["source"], "leads": [to_card(l) for l in res["leads"]],
                         "seconds": round(time.time() - job["started"])}
        job["state"] = "done"
    except finder.SearchError as e:
        job["state"], job["error"] = "error", str(e)
    except Exception:
        job["state"], job["error"] = "error", "Something went wrong during the search. Try again in a minute."


@app.post("/api/search")
def search(body: dict, request: Request):
    profile = body.get("profile") or {}
    if not (profile.get("sell") or "").strip():
        raise HTTPException(400, "Tell us what you sell. We use it to judge fit and write your emails.")
    if not profile.get("types") and not (profile.get("types_other") or "").strip():
        raise HTTPException(400, "Pick at least one kind of business, or type one in.")
    if not (profile.get("city") or "").strip():
        raise HTTPException(400, "Tell us which city to search around.")
    who, now = _visitor(request), time.time()
    _recent[who] = [t for t in _recent.get(who, []) if now - t < 3600]
    if len(_recent[who]) >= SEARCHES_PER_HOUR:
        raise HTTPException(429, "You've run a lot of searches this hour. Try again a bit later.")
    _recent[who].append(now)
    how_many = body.get("how_many") if body.get("how_many") in (20, 40, 60) else 20
    job_id = uuid.uuid4().hex
    JOBS[job_id] = {"state": "running", "progress": 0.0, "message": "Starting…", "log": [], "started": now}
    threading.Thread(target=_run, args=(job_id, profile, how_many), daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/search/{job_id}")
def search_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "That search has expired. Run it again.")
    return {k: job.get(k) for k in ("state", "progress", "message", "log", "error", "result")}


@app.post("/api/add-email")
def add_email(body: dict):
    job = JOBS.get(body.get("job_id") or "")
    lead = (job or {}).get("raw", {}).get(body.get("lead_id"))
    if not lead:
        raise HTTPException(404, "We lost track of that search. Run it again, then add the email.")
    out = finder.with_manual_email(lead, body.get("email") or "", body.get("profile") or {}, verify=finder.verify_email)
    if out is lead:
        raise HTTPException(400, "That doesn't look like an email address.")
    job["raw"][lead["id"]] = out
    return to_card(out)


@app.post("/api/draft")
def draft(body: dict):
    sender, lead = body.get("sender") or {}, body.get("lead") or {}
    if not lead.get("business_name"):
        raise HTTPException(400, "Missing the lead to write to.")
    if not claude():
        return emails.template_email(sender, lead)
    current = body.get("current") if body.get("rewrite") else None
    try:
        return emails.write_email(claude(), CLAUDE_MODEL, sender, lead, instruction=body.get("instruction") or "",
                                  current=current)
    except Exception:
        raise HTTPException(502, "The email didn't finish. Try again.")


app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")


@app.get("/")
def home():
    return FileResponse(HERE / "static" / "index.html")
