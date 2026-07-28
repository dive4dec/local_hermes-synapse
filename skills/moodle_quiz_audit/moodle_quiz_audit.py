#!/usr/bin/env python3
"""
Moodle Quiz Audit Tool (HTTP Session-Injection Mode)

Authenticates to Moodle by injecting the user's session cookie (written by the
local_hermesagent PHP plugin) into a requests.Session(). Fetches the quiz
overview report and access log report pages, parses the HTML tables with
BeautifulSoup, and flags suspicious student behavior:

  - Fast completion + high score
  - Non-campus IP addresses (configurable via MOODLE_AUDIT_CAMPUS_IPS env var)

No database access, no CDP, no Chrome binary required. Pure HTTP.

Usage:
    python3 moodle_quiz_audit.py --cmid 123 --moodle-userid 2
    python3 moodle_quiz_audit.py --cmid 123 --moodle-userid 2 --fast-mins 10 --fast-score 90
"""

import argparse
import ipaddress
import json
import os
import re
import sys
import time
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

# ── Fixed Constants ────────────────────────────────────────────────
SESSION_TTL = 1800  # 30 minutes — reject stale session files
LOG_CONTEXTLEVEL = 70  # 70 = Course Module Level


# ── Session file loading ───────────────────────────────────────────
def load_session_file(path: str) -> dict:
    """Load and validate a per-user msession JSON written by the Moodle plugin."""
    if not os.path.exists(path):
        raise RuntimeError(
            f"Session file not found: {path}\n"
            f"The Moodle plugin writes it on each API request. Make sure the "
            f"user has an active Moodle session and has sent a message in the chat."
        )
    with open(path) as f:
        data = json.load(f)
    for key in ("cookie_name", "cookie_value", "domain", "moodle_url"):
        if not data.get(key):
            raise RuntimeError(f"Session file {path} is missing '{key}'.")
    age = time.time() - int(data.get("written_at", 0))
    if SESSION_TTL > 0 and age > SESSION_TTL:
        raise RuntimeError(
            f"Session file {path} is stale ({int(age)}s old > {SESSION_TTL}s TTL). "
            f"Ask the user to send a fresh message in the Moodle chat, then retry."
        )
    return data


def resolve_session(moodle_userid: Optional[str] = None,
                    session_file: Optional[str] = None) -> dict:
    """Resolve a session dict from either an explicit path or a userid.

    Requires explicit userid or session_file — no auto-detect (security:
    auto-detect could load another user's session).
    """
    if session_file:
        return load_session_file(session_file)
    if moodle_userid:
        hermes_home = os.environ.get("HERMES_HOME", "/var/www/moodledata/.hermes")
        path = os.path.join(hermes_home, "run", f"msession_{moodle_userid}.json")
        return load_session_file(path)
    raise RuntimeError(
        "No session specified. Pass --moodle-userid <id> (required). "
        "The agent should obtain the userid from the chat context."
    )


# ── Campus IP classification (configurable via env var) ────────────
def load_campus_ranges() -> List[Tuple]:
    """Load campus IP ranges from MOODLE_AUDIT_CAMPUS_IPS env var.

    Format: comma-separated CIDR list, e.g.:
        MOODLE_AUDIT_CAMPUS_IPS=10.0.0.0/8,144.214.0.0/16,172.16.0.0/12

    If not set, returns a default that classifies private ranges as campus.
    Each entry is (ip_network, label).
    """
    env_val = os.environ.get("MOODLE_AUDIT_CAMPUS_IPS", "")
    if env_val.strip():
        ranges = []
        for cidr_str in env_val.split(","):
            cidr_str = cidr_str.strip()
            if not cidr_str:
                continue
            try:
                net = ipaddress.ip_network(cidr_str, strict=False)
                ranges.append((net, "Campus"))
            except ValueError:
                print(f"  [WARN] Invalid CIDR in MOODLE_AUDIT_CAMPUS_IPS: {cidr_str}", file=sys.stderr)
        if ranges:
            return ranges
        print("  [WARN] MOODLE_AUDIT_CAMPUS_IPS set but no valid CIDRs parsed. Using defaults.", file=sys.stderr)

    # Default: standard private ranges
    return [
        (ipaddress.ip_network("10.0.0.0/8"), "Private network"),
        (ipaddress.ip_network("172.16.0.0/12"), "Private network"),
        (ipaddress.ip_network("192.168.0.0/16"), "Private network"),
    ]


def classify_ip(ip: str, campus_ranges: List[Tuple]) -> Tuple[str, bool]:
    """Classify an IP address as campus or external using CIDR matching.

    Returns (network_profile, is_campus).
    """
    if not ip or ip == "System/Cron":
        return "System/Cron", True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return "Invalid IP", False
    for net, label in campus_ranges:
        if addr in net:
            return label, True
    return "External Network", False


# ── HTTP client with session injection ─────────────────────────────
class MoodleHTTPClient:
    """Lightweight HTTP client that injects a Moodle session cookie and
    fetches / parses HTML pages. No browser, no CDP — just requests + BeautifulSoup."""

    def __init__(self, session: dict):
        self.moodle_url = session["moodle_url"].rstrip("/")
        self.cookie_name = session["cookie_name"]
        self.cookie_value = session["cookie_value"]
        self.domain = session["domain"]

        self.http = requests.Session()
        self.http.cookies.set(
            self.cookie_name, self.cookie_value,
            domain=self.domain, path="/"
        )
        self.http.headers.update({
            "User-Agent": "Mozilla/5.0 (Hermes Agent Moodle Audit)",
            "Accept": "text/html,application/xhtml+xml",
        })
        # TLS verification: on by default. Set MOODLE_AUDIT_INSECURE=1 to disable
        # for self-signed cert environments.
        self.http.verify = os.environ.get("MOODLE_AUDIT_INSECURE", "0") != "1"
        if not self.http.verify:
            requests.packages.urllib3.disable_warnings()

    def verify_logged_in(self) -> None:
        """Check that the session is still valid (not redirected to login)."""
        resp = self.http.get(f"{self.moodle_url}/my/", timeout=15)
        if "login/index.php" in resp.url:
            raise RuntimeError(
                f"Session expired (redirected to {resp.url}). "
                f"Ask the user to reload the Moodle chat and retry."
            )

    def fetch(self, url: str, timeout: int = 30) -> str:
        """Fetch a URL and return the HTML text.

        Includes a per-request login-redirect guard so mid-run cookie expiry
        doesn't silently parse a login form as data.
        """
        resp = self.http.get(url, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        # Detect mid-run session expiry: Moodle redirects to /login/index.php
        if "login/index.php" in resp.url:
            raise RuntimeError(
                "Session expired mid-audit (redirected to login page). "
                "The session cookie may have timed out. Re-open the Moodle chat "
                "to refresh the session, then retry."
            )
        return resp.text

    def parse_table(self, html: str, table_class: Optional[str] = None) -> List[Dict]:
        """Parse an HTML table into a list of row dicts.
        Uses thead th as keys, tbody td as values.
        Falls back to first-row-as-header if no thead.

        If table_class is specified, searches for a table with that class FIRST
        (before falling back to the first table on the page).
        """
        soup = BeautifulSoup(html, "html.parser")

        # Search by class first (Moodle pages have many incidental layout tables)
        table = None
        if table_class:
            table = soup.find("table", class_=lambda c: table_class in (c or ""))
        if not table:
            table = soup.find("table")  # fallback to first table
        if not table:
            return []

        rows = []
        headers = []

        # Try thead first
        thead = table.find("thead")
        if thead:
            header_row = thead.find("tr")
            if header_row:
                headers = [th.get_text(strip=True) for th in header_row.find_all("th")]

        # If no thead, use first row of table as headers
        if not headers:
            first_tr = table.find("tr")
            if first_tr:
                cells = first_tr.find_all(["th", "td"])
                if cells:
                    headers = [c.get_text(strip=True) for c in cells]

        if not headers:
            return []

        # Parse data rows from tbody (or all rows if no tbody)
        tbody = table.find("tbody")
        all_rows = tbody.find_all("tr") if tbody else table.find_all("tr")

        # Skip the header row if it's in the main table body (no thead case)
        start_idx = 0
        if not thead and headers:
            start_idx = 1  # skip first row (used as headers)

        for i, tr in enumerate(all_rows):
            if i < start_idx:
                continue
            cells = tr.find_all("td")
            if not cells:
                continue
            row = {}
            for j, header in enumerate(headers):
                if j < len(cells):
                    row[header] = cells[j].get_text(strip=True)
                else:
                    row[header] = ""
            rows.append(row)

        return rows


# ── Data extraction helpers ────────────────────────────────────────
def extract_quiz_info(client: MoodleHTTPClient, cmid: int) -> dict:
    """Fetch quiz overview report and extract student data.
    Returns dict with quiz_id, quiz_name, max_grade, and attempts list."""
    url = (f"{client.moodle_url}/mod/quiz/report/index.php"
           f"?cmid={cmid}&report=overview&pagesize=10000")
    html = client.fetch(url)
    soup = BeautifulSoup(html, "html.parser")

    # Extract quiz name from page heading
    quiz_name = "Unknown Quiz"
    h2 = soup.find("h2")
    if h2:
        quiz_name = h2.get_text(strip=True)

    # Parse the overview table — Moodle uses 'generaltable' class for report tables
    rows = client.parse_table(html, table_class="generaltable")

    attempts = []
    for row in rows:
        # Moodle overview table columns: Full name, Grade, Time started,
        # Time finished, Duration, Attempts, etc.
        # Column names may vary by Moodle language; use flexible matching.
        name = row.get("Full name", row.get("fullname", row.get("Name", "")))
        grade = row.get("Grade", row.get("grade", ""))
        time_started = row.get("Time started", row.get("timestart", ""))
        time_finished = row.get("Time finished", row.get("timefinish", ""))
        duration = row.get("Duration", row.get("duration", ""))

        # Skip summary rows (Average, etc.)
        if not name or name in ("Average", "Overall average", "Group average",
                                "Overall Average", "Group Average"):
            continue
        # Skip rows with no grade
        if not grade or grade == "-":
            continue

        attempts.append({
            "name": name,
            "grade": grade,
            "time_started": time_started,
            "time_finished": time_finished,
            "duration": duration,
        })

    # Extract max grade from quiz info
    max_grade = _extract_max_grade(soup)

    return {
        "quiz_name": quiz_name,
        "max_grade": max_grade,
        "attempts": attempts,
    }


def _extract_max_grade(soup: BeautifulSoup) -> float:
    """Try to find the max grade from the page."""
    # Look for "Maximum grade" or similar in the page
    for label in soup.find_all(string=re.compile(r"Maximum grade|max.grade|sumgrades", re.I)):
        parent = label.parent
        if parent and parent.next_sibling:
            sibling_text = parent.next_sibling.strip() if hasattr(parent.next_sibling, 'strip') else str(parent.next_sibling).strip()
            if not sibling_text:
                continue
            try:
                return float(sibling_text)
            except (ValueError, AttributeError):
                pass
    # Fallback: look in meta or data attributes
    for tag in soup.find_all(attrs={"data-maxgrade": True}):
        try:
            return float(tag["data-maxgrade"])
        except ValueError:
            pass
    return 100.0  # default


def extract_ip_data(client: MoodleHTTPClient, cmid: int) -> Dict[str, List[str]]:
    """Fetch the access log report for the given cmid and extract IP addresses
    per student. Returns {student_name: [ip1, ip2, ...]}."""
    # The log report filters by modid (course module id)
    url = (f"{client.moodle_url}/report/log/index.php"
           f"?modid={cmid}&perpage=10000")
    html = client.fetch(url)

    # Moodle log report uses 'generaltable' class
    rows = client.parse_table(html, table_class="generaltable")

    # Moodle log table columns typically include:
    # Time, User, Event, IP (or similar names depending on language)
    user_ips: Dict[str, List[str]] = {}

    for row in rows:
        # Find user name and IP from the row
        user_name = None
        ip_addr = None

        for key, value in row.items():
            key_lower = key.lower()
            # Match user name columns — use exact column name patterns
            # to avoid false matches like "description" containing "ip"
            if key_lower in ("user full name", "user", "name", "fullname",
                             "affected user", "event context"):
                if user_name is None and value:
                    user_name = value
            # Match IP address column — require "ip" as a word, not substring
            if re.search(r'\bip\b', key_lower) or key_lower == "ip address":
                if value:
                    ip_addr = value

        if user_name and ip_addr:
            if user_name not in user_ips:
                user_ips[user_name] = []
            if ip_addr not in user_ips[user_name]:
                user_ips[user_name].append(ip_addr)

    return user_ips


def parse_duration_minutes(duration_str: str) -> Optional[float]:
    """Parse a Moodle duration string like '2 hrs 30 mins' or '45 secs' into minutes."""
    if not duration_str or duration_str == "-":
        return None
    total = 0.0
    # Match patterns like "2 hrs", "30 mins", "45 secs"
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*(hrs?|hours?|mins?|minutes?|secs?|seconds?)",
                             duration_str, re.I):
        value = float(match.group(1))
        unit = match.group(2).lower()
        if unit.startswith("hr") or unit.startswith("hour"):
            total += value * 60
        elif unit.startswith("min"):
            total += value
        elif unit.startswith("sec"):
            total += value / 60.0
    return total if total > 0 else None


def parse_grade_value(grade_str: str, max_grade: float) -> Tuple[Optional[float], Optional[float]]:
    """Parse a grade string like '85/100' or '85.00' into (raw_grade, percentage)."""
    if not grade_str or grade_str == "-":
        return None, None

    # Remove any HTML entities or extra whitespace
    grade_str = re.sub(r"\s+", " ", grade_str.strip())

    # Pattern: "85/100" or "85.00 / 100.00"
    slash_match = re.search(r"([\d.]+)\s*/\s*([\d.]+)", grade_str)
    if slash_match:
        raw = float(slash_match.group(1))
        maximum = float(slash_match.group(2))
        pct = (raw / maximum * 100) if maximum > 0 else 0
        return raw, pct

    # Pattern: just a number
    num_match = re.search(r"([\d.]+)", grade_str)
    if num_match:
        raw = float(num_match.group(1))
        pct = (raw / max_grade * 100) if max_grade > 0 else 0
        return raw, pct

    return None, None


# ── Core Audit Logic ───────────────────────────────────────────────
def run_audit(cmid: int, fast_mins: float = None, fast_score: float = 80.0,
              moodle_userid: str = None, session_file: str = None):
    """Main audit logic: fetch data, analyze, and print results."""

    print("=" * 80)
    print("  Moodle Quiz Audit Tool (HTTP Session-Injection Mode)")
    print(f"  Target quiz cmid={cmid}")
    if fast_mins:
        print(f"  [Threshold] Duration < {fast_mins} mins AND Score >= {fast_score}%")
    print("=" * 80)

    # ── Step 0: Load session and authenticate ──
    print("\n--- Step 0: Loading session ---")
    try:
        session = resolve_session(moodle_userid=moodle_userid, session_file=session_file)
    except RuntimeError as e:
        print(f"\n[ERROR] {e}")
        return

    client = MoodleHTTPClient(session)
    try:
        client.verify_logged_in()
        print(f"  Authenticated via session cookie ({session['cookie_name']})")
        print(f"  Moodle URL: {session['moodle_url']}")
    except RuntimeError as e:
        print(f"\n[ERROR] {e}")
        return

    # ── Step 1: Fetch quiz overview data ──
    print("\n--- Step 1: Fetching quiz overview report ---")
    try:
        quiz_info = extract_quiz_info(client, cmid)
    except Exception as e:
        print(f"\n[ERROR] Failed to fetch quiz overview: {e}")
        return

    quiz_name = quiz_info["quiz_name"]
    max_grade = quiz_info["max_grade"]
    attempts = quiz_info["attempts"]

    print(f"  Quiz Name:  {quiz_name}")
    print(f"  Max Grade:  {max_grade}")
    print(f"  Total attempts parsed: {len(attempts)}")

    if not attempts:
        print("  [WARN] No attempts found. The quiz may have no submissions yet.")
        return

    # ── Step 2: Fetch IP address data ──
    print("\n--- Step 2: Fetching access log for IP addresses ---")
    campus_ranges = load_campus_ranges()
    ip_env = os.environ.get("MOODLE_AUDIT_CAMPUS_IPS", "")
    if ip_env:
        print(f"  Campus IP ranges from MOODLE_AUDIT_CAMPUS_IPS: {ip_env}")
    else:
        print("  MOODLE_AUDIT_CAMPUS_IPS not set — using default private ranges.")
        print("  To configure campus-specific ranges, set MOODLE_AUDIT_CAMPUS_IPS")
        print("  in the Hermes .env file (Settings → .env editor).")

    try:
        user_ips = extract_ip_data(client, cmid)
        print(f"  IP data collected for {len(user_ips)} students")
    except Exception as e:
        print(f"  [WARN] Could not fetch IP data: {e}")
        user_ips = {}

    if not user_ips:
        print("  [WARN] No IP data collected — IP audit incomplete.")
        print("         Do NOT trust the 'no off-campus IPs' result below.")

    # ── Step 3: Analyze completion times ──
    print("\n--- Step 3: Analyzing completion times ---")
    suspicious_fast = []
    for att in attempts:
        duration_min = parse_duration_minutes(att["duration"])
        grade_raw, grade_pct = parse_grade_value(att["grade"], max_grade)

        line = f"  [Student] {att['name']:<25}: {att['duration']}"
        if grade_pct is not None:
            line += f"  (Score: {grade_pct:.1f}%)"

        if (fast_mins is not None
                and duration_min is not None
                and grade_pct is not None
                and duration_min < fast_mins
                and grade_pct >= fast_score):
            line += f"  <-- [!!! SUSPICIOUS: {grade_pct:.1f}% in {duration_min:.1f}m]"
            suspicious_fast.append({
                "name": att["name"],
                "duration_min": duration_min,
                "grade_pct": grade_pct,
            })

        print(line)

    # ── Step 4: IP Address Audit ──
    print("\n--- Step 4: IP Address Audit & Network Profiling ---")
    flagged_ips = []
    # Build a set of student names from attempts for cross-referencing
    attempt_names = {att["name"] for att in attempts}

    # Check IPs for students who appear in the attempts list
    # Use exact name matching only — substring matching merges students
    # with the same surname (e.g. "Lee" matches "Lee Chi Ming" and "Bradley")
    checked_names = set()
    for name in attempt_names:
        ips = user_ips.get(name, [])

        if ips:
            for ip in ips:
                net_profile, is_campus = classify_ip(ip, campus_ranges)
                status = f"[{net_profile}]"
                if not is_campus:
                    status += "  *** FLAGGED ***"
                    flagged_ips.append((name, ip, net_profile))
                print(f"  {name:<25}: {ip:<18}  {status}")
            checked_names.add(name)

    # Also show IPs for students in the log who aren't in attempts
    for name, ips in user_ips.items():
        if name not in checked_names:
            for ip in ips:
                net_profile, is_campus = classify_ip(ip, campus_ranges)
                status = f"[{net_profile}]"
                if not is_campus:
                    status += "  *** FLAGGED ***"
                    flagged_ips.append((name, ip, net_profile))
                print(f"  {name:<25}: {ip:<18}  {status}")

    # ── Summary ──
    print("\n" + "=" * 80)
    print("  AUDIT SUMMARY")
    print("=" * 80)
    print(f"  Total students with attempts: {len(attempt_names)}")

    if suspicious_fast:
        print(f"\n  [!] {len(suspicious_fast)} suspicious fast completion(s):")
        for s in suspicious_fast:
            print(f"      {s['name']}: {s['grade_pct']:.1f}% in {s['duration_min']:.1f}m")

    if flagged_ips:
        print(f"\n  [!] {len(flagged_ips)} non-campus IP connection(s):")
        for name, ip, profile in flagged_ips:
            print(f"      {name} connected from {ip} ({profile})")

    if not suspicious_fast and not flagged_ips:
        print("\n  No suspicious activity detected.")

    if not user_ips:
        print("\n  [!] IP audit was incomplete (no log data).")
        print("      The 'no off-campus IPs' result above is NOT reliable.")

    print("=" * 80)


# ── CLI Entry Point ────────────────────────────────────────────────
def parse_args():
    parser = argparse.ArgumentParser(
        description="Moodle Quiz Audit Tool (HTTP Session-Injection Mode)\n\n"
        "Authenticates via session cookie written by the local_hermesagent "
        "PHP plugin. No database access, no Chrome, no CDP."
    )
    parser.add_argument("--cmid", type=int, required=True,
                        help="Course Module ID of the quiz to audit")
    parser.add_argument("--fast-mins", type=float, default=None,
                        help="Suspicious completion time threshold in minutes")
    parser.add_argument("--fast-score", type=float, default=80.0,
                        help="Suspicious score percentage threshold (default: 80.0)")
    parser.add_argument("--moodle-userid", type=str, default=None, required=True,
                        help="Moodle user ID to load session file for "
                        "($HERMES_HOME/run/msession_<id>.json). Required — "
                        "auto-detect removed for security.")
    parser.add_argument("--session-file", type=str, default=None,
                        help="Explicit path to a session JSON file (overrides --moodle-userid)")
    return parser.parse_args()


def main():
    args = parse_args()
    run_audit(
        cmid=args.cmid,
        fast_mins=args.fast_mins,
        fast_score=args.fast_score,
        moodle_userid=args.moodle_userid,
        session_file=args.session_file,
    )


if __name__ == "__main__":
    main()
