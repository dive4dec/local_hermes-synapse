"""
moodle-bridge — Hermes plugin for Moodle integration.

Does what memory cannot:
  1. moodle_get_my_courses tool: returns courses the CURRENT user is enrolled in
  2. moodle_upload_file tool: uploads a file to a Moodle course as a resource
  3. moodle_audit_quiz tool: audit a quiz for integrity signals (fast completions,
     off-campus attempt IPs, SEB block events) — pure DB queries, in-process,
     no child processes, no session cookie required.

User identity is read from a per-session file written by the bridge:
  $HERMES_HOME/run/identity/<HERMES_SESSION_KEY>.identity.json
Because the ACP session id is hermes's per-session HERMES_SESSION_KEY (a
concurrency-safe ContextVar), two admins chatting at once each read their own
identity — no cross-attribution. The legacy single $HERMES_HOME/.moodle_identity
is still honored as a fallback for older bridge deployments.

Memory stores static knowledge (course IDs, quiz IDs). This plugin provides
per-user identity and Moodle API actions — things that change every session
and require Moodle's file/permission APIs.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import json
import tempfile
import ipaddress
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_MOODLE_CFG: Optional[dict] = None


# ---------------------------------------------------------------------------
# Moodle config parsing
# ---------------------------------------------------------------------------

def _parse_moodle_config(path: str) -> dict:
    """Extract DB credentials from Moodle's config.php without executing it."""
    text = open(path, "r", encoding="utf-8").read()
    cfg = {}
    for key in ["dbhost", "dbport", "dbname", "dbuser", "dbpass", "dbtype", "wwwroot", "prefix"]:
        m = re.search(rf'\$CFG->{key}\s*=\s*[\'"]([^\'"]*)[\'"]', text)
        if m:
            cfg[key] = m.group(1)
    cfg.setdefault("prefix", "mdl_")
    return cfg


def _get_moodle_cfg() -> Optional[dict]:
    global _MOODLE_CFG
    if _MOODLE_CFG is not None:
        return _MOODLE_CFG
    config_path = os.environ.get("MOODLE_CONFIG_PATH")
    if not config_path:
        logger.debug("MOODLE_CONFIG_PATH not set, moodle-bridge inactive")
        return None
    try:
        _MOODLE_CFG = _parse_moodle_config(config_path)
        return _MOODLE_CFG
    except Exception as e:
        logger.warning("Failed to parse Moodle config: %s", e)
        return None


# ---------------------------------------------------------------------------
# Database queries
# ---------------------------------------------------------------------------

def _query_user_courses(userid: int) -> List[dict]:
    """Return courses the given user is enrolled in, with their role."""
    import pymysql
    cfg = _get_moodle_cfg()
    if not cfg:
        return []
    conn = pymysql.connect(
        host=cfg["dbhost"], user=cfg["dbuser"],
        password=cfg["dbpass"], database=cfg["dbname"],
        connect_timeout=5, read_timeout=10,
    )
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute("""
                SELECT c.id, c.shortname, c.fullname, c.visible,
                       r.shortname AS role
                FROM {prefix}context ctx
                JOIN {prefix}enrol e ON e.courseid = ctx.instanceid
                JOIN {prefix}user_enrolments ue ON ue.enrolid = e.id
                JOIN {prefix}user u ON u.id = ue.userid
                JOIN {prefix}role_assignments ra
                  ON ra.contextid = ctx.id AND ra.userid = u.id
                JOIN {prefix}role r ON r.id = ra.roleid
                JOIN {prefix}course c ON c.id = ctx.instanceid
                WHERE u.id = %s AND ctx.contextlevel = 50
                  AND c.visible = 1
                ORDER BY c.shortname
            """.format(prefix=cfg["prefix"]), (userid,))
            return list(cur.fetchall())
    finally:
        conn.close()


def _query_user_by_username(username: str) -> Optional[dict]:
    import pymysql
    cfg = _get_moodle_cfg()
    if not cfg:
        return None
    conn = pymysql.connect(
        host=cfg["dbhost"], user=cfg["dbuser"],
        password=cfg["dbpass"], database=cfg["dbname"],
        connect_timeout=5, read_timeout=10,
    )
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(
                "SELECT id, username, firstname, lastname, email FROM {prefix}user "
                "WHERE username = %s AND deleted = 0 AND suspended = 0".format(prefix=cfg["prefix"]),
                (username,)
            )
            row = cur.fetchone()
            return row
    finally:
        conn.close()


def _db_connect():
    """Open a connection to the Moodle DB. Returns (conn, prefix) or (None, None)."""
    import pymysql
    cfg = _get_moodle_cfg()
    if not cfg:
        return None, None
    conn = pymysql.connect(
        host=cfg["dbhost"],
        port=int(cfg.get("dbport") or 3306),
        user=cfg["dbuser"],
        password=cfg["dbpass"], database=cfg["dbname"],
        connect_timeout=5, read_timeout=15,
    )
    return conn, cfg["prefix"]


# ---------------------------------------------------------------------------
# Current user — read from identity file written by the bridge
# ---------------------------------------------------------------------------

def _current_session_key() -> str:
    """Return the current ACP session id for THIS in-process tool call.

    Hermes binds HERMES_SESSION_KEY as a per-session ContextVar for ACP
    sessions (concurrency-safe). get_session_env() reads the ContextVar first
    and only falls back to os.environ for non-ACP (CLI/cron) runs. This is what
    lets two concurrent admins each see their own identity."""
    try:
        from gateway.session_context import get_session_env
        key = get_session_env("HERMES_SESSION_KEY", "")
        if key:
            return key
    except Exception:
        pass
    return os.environ.get("HERMES_SESSION_KEY", "")


def _read_identity_dict() -> Optional[dict]:
    """Read {username, userid} — prefer the per-session identity file, fall
    back to the legacy single $HERMES_HOME/.moodle_identity."""
    hermes_home = os.environ.get("HERMES_HOME", "")
    if not hermes_home:
        return None
    # 1) Per-session file: $HERMES_HOME/run/identity/<session_key>.identity.json
    session_key = _current_session_key()
    candidates = []
    if session_key:
        candidates.append(Path(hermes_home) / "run" / "identity" / f"{session_key}.identity.json")
    # 2) Legacy single file (older bridge / non-concurrent fallback)
    candidates.append(Path(hermes_home) / ".moodle_identity")
    for identity_file in candidates:
        try:
            if identity_file.exists():
                data = json.loads(identity_file.read_text())
                if data.get("username"):
                    return data
        except Exception as e:
            logger.debug("Failed to read identity file %s: %s", identity_file, e)
    return None


def _get_current_user() -> Optional[dict]:
    """Read the current Moodle user, scoped to this ACP session.

    The bridge writes a per-session identity file keyed by the ACP session id
    (== HERMES_SESSION_KEY) before each prompt. Because the session key is a
    concurrency-safe per-session ContextVar, two admins chatting at once each
    resolve their own identity — uploads/courses are never cross-attributed.
    """
    data = _read_identity_dict()
    if not data:
        return None
    username = data.get("username", "")
    if not username:
        return None
    # Look up full user info from DB
    user = _query_user_by_username(username)
    if user:
        return user
    # DB lookup failed — username doesn't exist
    logger.warning("Moodle user '%s' not found in database", username)
    return None


# ---------------------------------------------------------------------------
# Tools — actions memory cannot provide
# ---------------------------------------------------------------------------

AUDIT_QUIZ_SCHEMA = {
    "name": "moodle_audit_quiz",
    "description": (
        "Audit a Moodle quiz for integrity signals, using the live database "
        "directly (no HTML scraping). Returns: (1) every attempt with its "
        "duration and grade, flagging suspiciously fast high-scoring "
        "completions; (2) each attempt's submission IP address (from the "
        "logstore), optionally flagged as non-campus if campus_ips is given; "
        "(3) Safe Exam Browser access-block events for the quiz. Requires the "
        "calling user to be a site admin or a teacher/manager of the quiz's "
        "course. Note: attempt IP data only exists for the logstore retention "
        "window (see log_retention in the result) — audit soon after the quiz. "
        "Pass cmid (course module id) OR quiz name (+ course_id to "
        "disambiguate)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "cmid": {
                "type": "integer",
                "description": "Course module id of the quiz (preferred).",
            },
            "quiz": {
                "type": "string",
                "description": "Quiz name, if cmid is unknown.",
            },
            "course_id": {
                "type": "integer",
                "description": "Optional course id to disambiguate a quiz name.",
            },
            "fast_mins": {
                "type": "number",
                "description": (
                    "Flag attempts that finished in fewer than this many "
                    "minutes (e.g. 10 for a 50-min quiz). Omit to skip."
                ),
            },
            "fast_score": {
                "type": "number",
                "description": (
                    "Only flag a fast attempt if its score percentage is at "
                    "least this value (default 80)."
                ),
            },
            "campus_ips": {
                "type": "string",
                "description": (
                    "Optional comma-separated CIDR list of 'on campus / lab' "
                    "IPs (e.g. 10.1.210.0/24,144.214.0.0/16). Unset = list "
                    "the IPs without flagging anything."
                ),
            },
            "date_from": {
                "type": "string",
                "description": "Optional audit-window start (site timezone), e.g. '2026-03-25 00:00:00'.",
            },
            "date_to": {
                "type": "string",
                "description": "Optional audit-window end (site timezone).",
            },
        },
        "required": [],
    },
}

GET_MY_COURSES_SCHEMA = {
    "name": "moodle_get_my_courses",
    "description": (
        "Get the courses the current Moodle user is enrolled in, with their role. "
        "This is per-user — returns different results for each session. "
        "Use this instead of guessing course IDs from memory."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

UPLOAD_FILE_SCHEMA = {
    "name": "moodle_upload_file",
    "description": (
        "Upload a file to a Moodle course as a resource (file resource). "
        "Requires teacher/manager role. Uses Moodle's file API via a PHP helper script. "
        "Parameters: course_id (int), file_path (str, absolute path to the file), "
        "display_name (str, optional name shown in Moodle), "
        "visible (bool, optional, default false — upload hidden so only teachers "
        "can see it; set true only when the user explicitly asks to publish/show "
        "it to students)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "course_id": {
                "type": "integer",
                "description": "Moodle course ID (from moodle_get_my_courses or memory)",
            },
            "file_path": {
                "type": "string",
                "description": "Absolute path to the file to upload (e.g. /var/www/moodledata/.hermes/cron/output/quiz.pdf)",
            },
            "display_name": {
                "type": "string",
                "description": "Display name in Moodle (defaults to filename)",
            },
            "visible": {
                "type": "boolean",
                "description": "Whether the resource is visible to students (default false — hidden, teachers only)",
            },
        },
        "required": ["course_id", "file_path"],
    },
}


def _handle_get_my_courses(args: dict, **kwargs) -> str:
    """Handler for moodle_get_my_courses tool."""
    user = _get_current_user()
    if not user:
        return json.dumps({"error": "No Moodle user identified for this session"})
    try:
        courses = _query_user_courses(user["id"])
        return json.dumps({
            "user": f"{user['firstname']} {user['lastname']}".strip() or user["username"],
            "userid": user["id"],
            "courses": [
                {
                    "id": c["id"],
                    "shortname": c["shortname"],
                    "fullname": c["fullname"],
                    "role": c.get("role", "?"),
                }
                for c in courses
            ],
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Failed to query courses: {e}"})


def _handle_upload_file(args: dict, **kwargs) -> str:
    """Handler for moodle_upload_file tool — shells out to a PHP helper."""
    course_id = args.get("course_id")
    file_path = args.get("file_path", "")
    display_name = args.get("display_name") or os.path.basename(file_path)
    # Default to hidden (visible=0) so solution files etc. are only
    # accessible to teachers until explicitly published.
    visible = 1 if args.get("visible") else 0

    if not course_id or not file_path:
        return json.dumps({"error": "course_id and file_path are required"})
    if not os.path.exists(file_path):
        return json.dumps({"error": f"File not found: {file_path}"})
    user = _get_current_user()
    if not user:
        return json.dumps({"error": "No Moodle user identified for this session"})

    # The stored filename must include the original file's extension so
    # Moodle can determine the MIME type and serve it via pluginfile.php.
    # The display_name is used for the resource title only.
    src_filename = os.path.basename(file_path)
    src_ext = os.path.splitext(src_filename)[1]  # e.g. ".pdf"
    if src_ext and not display_name.lower().endswith(src_ext.lower()):
        stored_filename = display_name + src_ext
    else:
        stored_filename = display_name

    # Write a PHP helper that creates a resource module + stores the file.
    # We avoid add_moduleinfo() — it's fragile in CLI mode and needs many
    # fields.  Instead we create the records directly and let Moodle's
    # file storage handle the actual file.
    config_path = os.environ.get("MOODLE_CONFIG_PATH", "/var/www/html/config.php")
    php_script = f"""<?php
define('CLI_SCRIPT', true);
$_SERVER['REQUEST_URI'] = '/edb/';
$_SERVER['SCRIPT_NAME'] = '/edb/admin/cli/foo.php';
require_once('{config_path}');
global $CFG, $DB;
require_once($CFG->libdir . '/filelib.php');
require_once($CFG->dirroot . '/course/lib.php');

$courseid = {course_id};
$filepath = '{file_path}';
$displayname = '{display_name}';
$storedfilename = '{stored_filename}';
$userid = {user['id']};
$visible = {visible};

// 1. Create the resource instance
$resource = new stdClass();
$resource->course = $courseid;
$resource->name = $displayname;
$resource->displayoptions = serialize(array("display" => "inline"));
$resource->timemodified = time();
$resource->timecreated = time();
$resource->id = $DB->insert_record('resource', $resource);

// 2. Create the course module (hidden by default — teachers only)
$moduleid = $DB->get_field('modules', 'id', array('name' => 'resource'));
$cm = new stdClass();
$cm->course = $courseid;
$cm->module = $moduleid;
$cm->instance = $resource->id;
$cm->section = 0;
$cm->visible = $visible;
$cm->added = time();
$cm->id = $DB->insert_record('course_modules', $cm);

// 3. Add to course section
course_add_cm_to_section($courseid, $cm->id, 0);

// 4. Store the file in the module's context
// NOTE: Moodle's mod_resource view.php looks for files with itemid=0,
// not the resource instance id. Using itemid=0 is the correct convention.
$context = context_module::instance($cm->id);
$fs = get_file_storage();
$filerecord = array(
    'contextid' => $context->id,
    'component' => 'mod_resource',
    'filearea' => 'content',
    'itemid' => 0,
    'filepath' => '/',
    'filename' => $storedfilename,
    'userid' => $userid,
);
$storedfile = $fs->create_file_from_pathname($filerecord, $filepath);

echo json_encode(array(
    'cmid' => $cm->id,
    'resource_id' => $resource->id,
    'file_id' => $storedfile->get_id(),
    'name' => $displayname,
    'filename' => $storedfilename,
    'course' => $courseid,
    'visible' => $visible,
));
"""

    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".php", delete=False) as f:
            f.write(php_script)
            script_path = f.name

        result = subprocess.run(
            ["php", script_path],
            capture_output=True, text=True, timeout=30,
        )
        os.unlink(script_path)

        if result.returncode != 0:
            return json.dumps({"error": f"PHP script failed: {result.stderr}"})

        return result.stdout.strip()
    except Exception as e:
        return json.dumps({"error": f"Upload failed: {e}"})


# ---------------------------------------------------------------------------
# moodle_audit_quiz — in-process DB audit (no child process, no session cookie)
# ---------------------------------------------------------------------------

def _audit_resolve_cmid(cur, prefix, cmid=None, quiz=None, course_id=None):
    """Resolve (cmid, quiz_id, course_id, quiz_name). Returns (None, err) on failure."""
    if cmid:
        cur.execute(
            "SELECT cm.id AS cmid, cm.instance AS quizid, q.name, q.course, c.shortname "
            "FROM {p}course_modules cm "
            "JOIN {p}modules m ON m.id = cm.module "
            "JOIN {p}quiz q ON q.id = cm.instance "
            "JOIN {p}course c ON c.id = q.course "
            "WHERE m.name = 'quiz' AND cm.id = %s".format(p=prefix),
            (cmid,),
        )
        row = cur.fetchone()
        if not row:
            return None, f"cmid {cmid} is not a quiz course module"
        return (row["cmid"], row["quizid"], row["course"], f'{row["name"]} ({row["shortname"]})'), None
    if quiz:
        sql = (
            "SELECT cm.id AS cmid, cm.instance AS quizid, q.name, q.course, c.shortname "
            "FROM {p}course_modules cm "
            "JOIN {p}modules m ON m.id = cm.module "
            "JOIN {p}quiz q ON q.id = cm.instance "
            "JOIN {p}course c ON c.id = q.course "
            "WHERE m.name = 'quiz' AND q.name = %s"
        )
        params = [quiz]
        if course_id:
            sql += " AND q.course = %s"
            params.append(course_id)
        cur.execute(sql.format(p=prefix), tuple(params))
        rows = cur.fetchall()
        if not rows:
            return None, f"no quiz named {quiz!r}" + (f" in course {course_id}" if course_id else "")
        if len(rows) > 1:
            opts = ", ".join(f'cmid={r["cmid"]} ({r["shortname"]})' for r in rows)
            return None, f"quiz {quiz!r} is ambiguous — candidates: {opts}"
        row = rows[0]
        return (row["cmid"], row["quizid"], row["course"], f'{row["name"]} ({row["shortname"]})'), None
    return None, "provide cmid, or quiz (optionally with course_id)"


def _audit_load_attempts(cur, prefix, cmid, course_id, date_from, date_to):
    """All non-preview attempts with duration/grade + quiz max grade.

    Returns (attempts, warn) where attempts is a list of dicts and warn is an
    optional note about excluded previews."""
    # quiz max grade
    cur.execute(
        "SELECT q.grade AS maxgrade, q.name AS qname "
        "FROM {p}course_modules cm "
        "JOIN {p}modules m ON m.id = cm.module "
        "JOIN {p}quiz q ON q.id = cm.instance "
        "WHERE m.name='quiz' AND cm.id=%s".format(p=prefix),
        (cmid,),
    )
    maxgrade = (cur.fetchone() or {}).get("maxgrade")
    try:
        maxgrade = float(maxgrade) if maxgrade is not None else None
    except (TypeError, ValueError):
        maxgrade = None

    timefilter, params = [], []
    if date_from is not None:
        timefilter.append("a.timestart >= %s")
        params.append(date_from)
    if date_to is not None:
        timefilter.append("a.timestart <= %s")
        params.append(date_to)
    tf = ("WHERE " + " AND ".join(timefilter) + " AND") if timefilter else "WHERE"

    cur.execute(
        "SELECT a.id, a.userid, a.timestart, a.timefinish, a.sumgrades, a.preview, "
        "       u.firstname, u.lastname, u.email "
        "FROM {p}quiz_attempts a "
        "JOIN {p}user u ON u.id = a.userid "
        "JOIN {p}quiz q ON q.id = a.quiz "
        "JOIN {p}course_modules cm ON cm.instance = q.id "
        "JOIN {p}modules m ON m.id = cm.module AND m.name='quiz' "
        "{tf} cm.id = %s "
        "ORDER BY a.timestart ASC".format(p=prefix, tf=tf),
        tuple(params + [cmid]),
    )
    attempts, n_preview = [], 0
    for r in cur.fetchall():
        duration_min = None
        if r["timefinish"] and r["timestart"]:
            duration_min = round((r["timefinish"] - r["timestart"]) / 60.0, 1)
        try:
            sumg = float(r["sumgrades"]) if r["sumgrades"] is not None else None
        except (TypeError, ValueError):
            sumg = None
        grade_pct = None
        if sumg is not None and maxgrade:
            grade_pct = round(sumg / maxgrade * 100.0, 1)
        if r["preview"]:
            n_preview += 1
            continue
        attempts.append({
            "attempt_id": r["id"],
            "student": f'{r["firstname"]} {r["lastname"]}'.strip() or r["email"],
            "email": r["email"],
            "started": datetime.fromtimestamp(r["timestart"]).strftime("%Y-%m-%d %H:%M:%S") if r["timestart"] else None,
            "duration_min": duration_min,
            "grade": sumg,
            "grade_pct": grade_pct,
        })
    warn = f"{n_preview} preview attempt(s) excluded from results." if n_preview else None
    return attempts, maxgrade, warn


def _audit_submissions(cur, prefix, cmid, attempts):
    r"""Collect the IP(s) a student used for each attempt, from mod_quiz events
    keyed by objectid = quiz_attempts.id:
      - \mod_quiz\event\attempt_viewed     (student opens the attempt)
      - \mod_quiz\event\attempt_updated    (student answers / autosaves)
      - \mod_quiz\event\attempt_submitted  (final submit)
    These fire for virtually every attempt (unlike attempt_submitted alone,
    which only fires on final submit), so they are the reliable per-attempt IP
    source. Returns ({attempt_id: {ip, ips[], origin, submitted}}, retention_note)."""
    try:
        cur.execute(
            "SELECT MIN(timecreated) mn, MAX(timecreated) mx FROM {p}logstore_standard_log".format(p=prefix)
        )
        rr = cur.fetchone() or {}
        retention_note = None
        if rr.get("mn"):
            retention_note = (
                "logstore window: {a} to {b} — attempt IPs only exist for events "
                "inside this window (older attempts have no logged IP)".format(
                    a=datetime.fromtimestamp(rr["mn"]).strftime("%Y-%m-%d"),
                    b=datetime.fromtimestamp(rr["mx"]).strftime("%Y-%m-%d"),
                )
            )
    except Exception as e:
        retention_note = f"logstore retention check failed: {e}"

    by_attempt = {}
    ids = [a["attempt_id"] for a in attempts]
    if ids:
        qm = ",".join("%s" for _ in ids)
        ev = [r"\mod_quiz\event\attempt_viewed",
              r"\mod_quiz\event\attempt_updated",
              r"\mod_quiz\event\attempt_submitted"]
        cur.execute(
            "SELECT objectid, ip, origin, timecreated FROM {p}logstore_standard_log "
            "WHERE eventname IN (%s,%s,%s) AND objecttable='quiz_attempts' "
            "AND objectid IN ({qm}) AND ip IS NOT NULL AND ip <> '' "
            "ORDER BY timecreated ASC".format(p=prefix, qm=qm),
            tuple(ev) + tuple(ids),
        )
        for r in cur.fetchall():
            aid = r["objectid"]
            d = by_attempt.get(aid)
            if d is None:
                d = {"ip": None, "ips": [], "origin": None, "submitted": None}
                by_attempt[aid] = d
            d["ip"] = r["ip"]                      # ASC => last (latest) event wins
            d["origin"] = r["origin"]
            d["submitted"] = datetime.fromtimestamp(r["timecreated"]).strftime("%Y-%m-%d %H:%M:%S")
            if r["ip"] not in d["ips"]:
                d["ips"].append(r["ip"])
    return by_attempt, retention_note


def _audit_seb_events(cur, prefix, cmid, quizid):
    """SEB access-block events for this quiz (component='Safe Exam Browser access
    rules', course-module context). Best-effort: never raises."""
    events = []
    try:
        cur.execute(
            "SELECT l.relateduserid, l.userid, l.ip, l.timecreated, l.other, "
            "       u.firstname, u.lastname, u.email "
            "FROM {p}logstore_standard_log l "
            "LEFT JOIN {p}user u ON u.id = l.relateduserid "
            "WHERE l.component='Safe Exam Browser access rules' "
            "  AND l.contextlevel=70 AND l.contextinstanceid=%s".format(p=prefix),
            (cmid,),
        )
        for r in cur.fetchall():
            other = r.get("other") or ""
            # Confirm the event references our quiz (other.quizid), when present.
            qm = re.search(r'"quizid"\s*:\s*(\d+)', other)
            if qm and int(qm.group(1)) != quizid:
                continue
            reason_m = re.search(r"The reason was '([^']*)'", other)
            events.append({
                "student": (f'{r["firstname"]} {r["lastname"]}'.strip() if r.get("firstname") else None)
                            or r.get("email") or "unknown",
                "ip": r.get("ip"),
                "time": datetime.fromtimestamp(r["timecreated"]).strftime("%Y-%m-%d %H:%M:%S") if r.get("timecreated") else None,
                "reason": reason_m.group(1) if reason_m else None,
            })
        events.sort(key=lambda e: e["time"] or "")
    except Exception as e:
        events = [{"error": f"SEB event lookup failed: {e}"}]
    return events


def _parse_campus_ranges(s: str):
    ranges = []
    for part in (s or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ranges.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            ranges.append(("invalid", part))
    return ranges


def _handle_audit_quiz(args: dict, **kwargs) -> str:
    """Handler for moodle_audit_quiz — all reads are in-process SQL."""
    import pymysql
    user = _get_current_user()
    if not user:
        return json.dumps({"error": "No Moodle user identified for this session"})

    fast_mins = args.get("fast_mins")
    fast_score = float(args.get("fast_score", 80.0))
    campus_raw = args.get("campus_ips") or os.environ.get("MOODLE_AUDIT_CAMPUS_IPS", "")
    campus = _parse_campus_ranges(campus_raw)

    try:
        conn, prefix = _db_connect()
        if not conn:
            return json.dumps({"error": "Moodle DB not configured"})
        try:
            with conn.cursor(pymysql.cursors.DictCursor) as cur:
                resolved, err = _audit_resolve_cmid(cur, prefix,
                                                    args.get("cmid"), args.get("quiz"),
                                                    args.get("course_id"))
                if err:
                    return json.dumps({"error": err})
                cmid, quizid, course_id, quiz_label = resolved

                # --- Authorisation: course staff or site admin. Match the user's
                # role shortnames/archetypes at the course + site context against
                # a staff set. This is version/naming-robust (handles standard
                # 'editing teacher' as well as this site's 'editingteacher').
                STAFF_ROLES = {
                    "manager", "site administrator", "siteadmin", "coursecreator",
                    "course creator", "editingteacher", "editing teacher",
                    "teacher", "noneditingteacher", "non-editing teacher",
                }
                cur.execute(
                    "SELECT r.shortname, r.archetype, ctx.contextlevel FROM {p}context ctx "
                    "JOIN {p}role_assignments ra ON ra.contextid = ctx.id AND ra.userid = %s "
                    "JOIN {p}role r ON r.id = ra.roleid "
                    "WHERE (ctx.contextlevel = 10 OR (ctx.contextlevel = 50 AND ctx.instanceid = %s))"
                    .format(p=prefix),
                    (user["id"], course_id),
                )
                role_rows = cur.fetchall()
                is_siteadmin = False
                authorised = False
                for rr in role_rows:
                    token = (rr.get("shortname") or "").lower()
                    arch = (rr.get("archetype") or "").lower()
                    if token in STAFF_ROLES or arch in STAFF_ROLES:
                        authorised = True
                        if (rr.get("contextlevel") == 10) and token in (
                            "manager", "site administrator", "siteadmin"):
                            is_siteadmin = True
                if not authorised:
                    shown = sorted({(r.get("shortname") or "?") for r in role_rows})
                    who = f'{user["firstname"]} {user["lastname"]}'.strip()
                    return json.dumps({
                        "error": (
                            f"{who} is not a teacher/manager/admin of this course "
                            f"(roles: {', '.join(shown) or 'none'}). "
                            "Quiz audit is restricted to course staff and site admins."
                        ),
                    })

                # --- Time window (site timezone) ---
                tz = None
                try:
                    cur.execute(
                        "SELECT value FROM {p}config WHERE name='timezone'"
                        .format(p=prefix))
                    row = cur.fetchone()
                    tz = (row or {}).get("value") or None
                except Exception:
                    pass

                def ts(s):
                    # naive string -> unix epoch in the site timezone
                    try:
                        import zoneinfo
                        zi = zoneinfo.ZoneInfo(tz) if tz else None
                        return int(datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
                                   .replace(tzinfo=zi).timestamp())
                    except Exception:
                        return int(datetime.strptime(s, "%Y-%m-%d").timestamp())

                date_from = ts(args["date_from"]) if args.get("date_from") else None
                date_to = ts(args["date_to"]) if args.get("date_to") else None

                attempts, maxgrade, warn = _audit_load_attempts(
                    cur, prefix, cmid, course_id, date_from, date_to)
                subs, retention_note = _audit_submissions(cur, prefix, cmid, attempts)
                seb = _audit_seb_events(cur, prefix, cmid, quizid)

                flagged = []
                flagged_ids = set()
                for a in attempts:
                    s = subs.get(a["attempt_id"])
                    a["submission"] = s
                    ip = (s or {}).get("ip") if s else None
                    a["ip"] = ip
                    a["ips"] = (s or {}).get("ips", []) if s else []
                    a["ip_campus"] = None
                    if campus and a["ips"]:
                        valid = []
                        for one in a["ips"]:
                            if not one or one == "System/Cron":
                                continue
                            try:
                                valid.append(ipaddress.ip_address(one))
                            except ValueError:
                                pass
                        if valid:
                            # out-of-campus if ANY observed IP is outside all ranges
                            a["ip_campus"] = all(
                                any(v in net for net in campus
                                    if not (isinstance(net, tuple) and net[0] == "invalid"))
                                for v in valid
                            )
                    reasons = []
                    if (fast_mins is not None and a["duration_min"] is not None
                            and a["grade_pct"] is not None
                            and a["duration_min"] < float(fast_mins)
                            and a["grade_pct"] >= fast_score):
                        reasons.append(f"fast completion: {a['grade_pct']}% in {a['duration_min']} min")
                    if a["ip_campus"] is False:
                        offending = []
                        for one in a.get("ips", []):
                            if not one or one == "System/Cron":
                                continue
                            try:
                                v = ipaddress.ip_address(one)
                            except ValueError:
                                continue
                            if not any(v in net for net in campus
                                       if not (isinstance(net, tuple) and net[0] == "invalid")):
                                offending.append(one)
                        reasons.append(f"non-campus IP: {', '.join(offending)}")
                    if reasons and a["attempt_id"] not in flagged_ids:
                        flagged_ids.add(a["attempt_id"])
                        a["flag"] = "; ".join(reasons)
                        flagged.append(a)

                return json.dumps({
                    "quiz": quiz_label,
                    "cmid": cmid,
                    "course_id": course_id,
                    "auditor": f'{user["firstname"]} {user["lastname"]}'.strip() or user["username"],
                    "auditor_site_admin": is_siteadmin,
                    "timezone": tz,
                    "max_grade": maxgrade,
                    "attempts": attempts,
                    "flags": [
                        {"student": a["student"], "attempt_id": a["attempt_id"],
                         "flag": a["flag"], "ip": a["ip"], "duration_min": a["duration_min"],
                         "grade_pct": a["grade_pct"]}
                        for a in flagged
                    ],
                    "seb_access_blocks": seb,
                    "notes": [n for n in (retention_note, warn) if n],
                }, indent=2, default=str)
        finally:
            conn.close()
    except Exception as e:
        return json.dumps({"error": f"Audit failed: {e}"})


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------

def register(ctx) -> None:
    """Register moodle-bridge tools."""
    cfg = _get_moodle_cfg()
    if not cfg:
        logger.info("moodle-bridge: MOODLE_CONFIG_PATH not set — plugin inactive")
        return

    # Tools: actions memory cannot provide
    # User identity is read from $HERMES_HOME/.moodle_identity (written by the
    # bridge before each prompt) — no on_session_start hook needed.
    ctx.register_tool(
        name="moodle_get_my_courses",
        toolset="moodle",
        schema=GET_MY_COURSES_SCHEMA,
        handler=_handle_get_my_courses,
    )
    ctx.register_tool(
        name="moodle_upload_file",
        toolset="moodle",
        schema=UPLOAD_FILE_SCHEMA,
        handler=_handle_upload_file,
    )
    ctx.register_tool(
        name="moodle_audit_quiz",
        toolset="moodle",
        schema=AUDIT_QUIZ_SCHEMA,
        handler=_handle_audit_quiz,
    )

    logger.info("moodle-bridge registered: 3 tools")
