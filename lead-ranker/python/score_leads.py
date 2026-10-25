"""Score small-business leads: rule checks in code, judgment calls by Claude.

Usage:
    python score_leads.py leads.csv intake.json            # uses Claude (needs ANTHROPIC_API_KEY)
    python score_leads.py leads.csv intake.json --no-llm   # keyword fallback, no API needed
    add --skip-mx to skip the email domain DNS check (for fake test data)
"""
import csv, json, os, re, sys
from datetime import date, datetime
from urllib.parse import urlparse

FREE_DOMAINS = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com", "icloud.com", "live.com"}
DISPOSABLE = {"mailinator.com", "10minutemail.com", "guerrillamail.com", "tempmail.com"}
ROLE_PREFIXES = {"info", "contact", "hello", "office", "admin", "sales", "support", "owner", "team", "service"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")


# ---------- rule checks (deterministic) ----------
def has_mx(domain):
    """True / False if checkable, None if DNS lookup isn't possible."""
    if "--skip-mx" in sys.argv:
        return None
    try:
        import dns.resolver
        return len(dns.resolver.resolve(domain, "MX", lifetime=5)) > 0
    except ImportError:
        return None
    except Exception as e:
        name = type(e).__name__
        return False if name in ("NXDOMAIN", "NoAnswer") else None


def email_type(email, website):
    local, domain = email.lower().split("@", 1)
    if domain in FREE_DOMAINS:
        return "free"
    if local in ROLE_PREFIXES:
        return "role"
    site = urlparse(website).netloc.lower().removeprefix("www.") if website else ""
    return "personal" if site and domain == site else "role"


def days_since(d):
    try:
        return (date.today() - datetime.strptime(d.strip(), "%Y-%m-%d").date()).days
    except (ValueError, AttributeError):
        return None


def rule_checks(lead):
    email = (lead.get("email") or "").strip()
    out = {"reasons": [], "reject": False, "points": 0}

    if "closed" in (lead.get("status") or "").lower():
        out["reject"] = True
        out["reasons"].append("Business appears closed.")
    if not EMAIL_RE.match(email):
        out["reject"] = True
        out["reasons"].append("No valid email.")
        out["email_type"], out["email_valid"] = None, False
        return out

    domain = email.split("@", 1)[1].lower()
    mx = has_mx(domain)
    if domain in DISPOSABLE or mx is False:
        out["reject"] = True
        out["reasons"].append("Email domain cannot receive mail.")
    out["email_valid"] = not out["reject"]
    if mx is None:
        out["reasons"].append("MX not checked.")

    etype = email_type(email, lead.get("website"))
    out["email_type"] = etype
    out["points"] += {"personal": 30, "role": 15, "free": 10}[etype]
    out["reasons"].append(f"{etype.capitalize()} email.")

    age = days_since(lead.get("last_review_date"))
    if age is not None and age <= 90:
        out["points"] += 20
        out["reasons"].append("Reviewed in last 90 days.")
    elif age is not None and age <= 365:
        out["points"] += 10
        out["reasons"].append("Reviewed in last 12 months.")
    else:
        out["reasons"].append("No review in last 12 months.")
    return out


# ---------- judgment calls (Claude, or keyword fallback) ----------
def judge_with_claude(leads, intake):
    import anthropic
    client = anthropic.Anthropic()
    slim = [{k: l.get(k, "") for k in ("business_name", "address", "industry", "contact_name",
                                        "contact_title", "review_count")} for l in leads]
    prompt = f"""Ideal customer profile:
{json.dumps(intake, indent=2)}

For each lead below, decide:
- industry_match: does the business type match the profile's customer types?
- location_size_match: is it inside the service area AND roughly the right size?
- decision_maker: is the named contact likely the buying decision maker? (false if no name)
- note: one short sentence explaining your judgment.

Leads:
{json.dumps(slim, indent=2)}

Return ONLY a JSON array, same order as the leads, each item:
{{"industry_match": bool, "location_size_match": bool, "decision_maker": bool, "note": str}}"""
    msg = client.messages.create(
        model=os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5"),
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in msg.content if b.type == "text")
    return json.loads(re.sub(r"```(json)?", "", text).strip())


def judge_with_keywords(leads, intake):
    types = [t.lower() for t in intake.get("customer_types", [])]
    titles = [t.lower() for t in intake.get("decision_maker", [])]
    city = intake.get("service_area", "").split(",")[0].lower()
    results = []
    for l in leads:
        ind = any(t in (l.get("industry") or "").lower() for t in types)
        loc = bool(city) and city in (l.get("address") or "").lower()
        dm = bool(l.get("contact_name")) and any(t in (l.get("contact_title") or "").lower() for t in titles)
        results.append({"industry_match": ind, "location_size_match": loc,
                        "decision_maker": dm, "note": "Keyword match (no LLM)."})
    return results


# ---------- combine ----------
def score(leads, intake, use_llm=True):
    judgments = judge_with_claude(leads, intake) if use_llm else judge_with_keywords(leads, intake)
    scored = []
    for lead, j in zip(leads, judgments):
        r = rule_checks(lead)
        pts, reasons = r["points"], r["reasons"]
        if lead.get("contact_name"):
            pts += 20 if j.get("decision_maker") else 10
            reasons.append("Decision maker named." if j.get("decision_maker") else "Contact named.")
        else:
            reasons.append("No contact name.")
        if j.get("industry_match"):
            pts += 15
        if j.get("location_size_match"):
            pts += 15
        reasons.append(j.get("note", ""))

        tier = "Reject" if r["reject"] else "A" if pts >= 70 else "B" if pts >= 50 else "C"
        scored.append({**lead, "email_type": r.get("email_type"), "email_valid": r.get("email_valid"),
                       "score": 0 if r["reject"] else pts, "tier": tier,
                       "reasons": " ".join(x for x in reasons if x)})
    return sorted(scored, key=lambda x: x["score"], reverse=True)


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    leads = list(csv.DictReader(open(sys.argv[1], newline="", encoding="utf-8")))
    intake = json.load(open(sys.argv[2], encoding="utf-8"))
    results = score(leads, intake, use_llm="--no-llm" not in sys.argv)

    json.dump(results, open("scored_leads.json", "w"), indent=2)
    with open("scored_leads.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=results[0].keys())
        w.writeheader()
        w.writerows(results)
    for r in results:
        print(f"{r['tier']:>6}  {r['score']:>3}  {r['business_name']:<22} {r['reasons']}")


if __name__ == "__main__":
    main()
