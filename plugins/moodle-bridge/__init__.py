"""
moodle-bridge — Hermes plugin for Moodle integration.

Does what memory cannot:
  1. moodle_get_my_courses tool: returns courses the CURRENT user is enrolled in
  2. moodle_upload_file tool: uploads a file to a Moodle course as a resource

User identity is read from $HERMES_HOME/.moodle_identity, written by the bridge
before each prompt. The shared Hermes subprocess is single-threaded (prompts are
serialized), so this is safe — the identity file always reflects the current user.

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
    for key in ["dbhost", "dbname", "dbuser", "dbpass", "dbtype", "wwwroot", "prefix"]:
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


# ---------------------------------------------------------------------------
# Current user — read from identity file written by the bridge
# ---------------------------------------------------------------------------

def _get_current_user() -> Optional[dict]:
    """Read the current Moodle user from $HERMES_HOME/.moodle_identity.

    The bridge writes this file before each prompt. Because the Hermes ACP
    subprocess is single-threaded (prompts are serialized), the file always
    reflects the user whose prompt is currently being processed.
    """
    hermes_home = os.environ.get("HERMES_HOME", "")
    if not hermes_home:
        return None
    identity_file = Path(hermes_home) / ".moodle_identity"
    if not identity_file.exists():
        return None
    try:
        data = json.loads(identity_file.read_text())
        username = data.get("username", "")
        userid = data.get("userid", 0)
        if not username:
            return None
        # Look up full user info from DB
        user = _query_user_by_username(username)
        if user:
            return user
        # Fallback: construct minimal user from identity file
        if userid:
            return {"id": userid, "username": username, "firstname": "", "lastname": ""}
        return None
    except Exception as e:
        logger.warning("Failed to read moodle identity: %s", e)
        return None


# ---------------------------------------------------------------------------
# Tools — actions memory cannot provide
# ---------------------------------------------------------------------------

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
        "display_name (str, optional name shown in Moodle)."
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

    if not course_id or not file_path:
        return json.dumps({"error": "course_id and file_path are required"})
    if not os.path.exists(file_path):
        return json.dumps({"error": f"File not found: {file_path}"})
    user = _get_current_user()
    if not user:
        return json.dumps({"error": "No Moodle user identified for this session"})

    # Write a small PHP helper that uses Moodle's file API
    php_script = f"""<?php
define('CLI_SCRIPT', true);
$_SERVER['REQUEST_URI'] = '/edb/';
$_SERVER['SCRIPT_NAME'] = '/edb/admin/cli/foo.php';
require_once('{os.environ.get("MOODLE_CONFIG_PATH", "/var/www/html/public/config.php")}');
global $CFG, $DB;
require_once($CFG->libdir . '/filelib.php');

$courseid = {course_id};
$filepath = '{file_path}';
$displayname = '{display_name}';
$userid = {user['id']};

$context = context_course::instance($courseid);
$fs = get_file_storage();

$filerecord = array(
    'contextid' => $context->id,
    'component' => 'mod_resource',
    'filearea' => 'content',
    'itemid' => 0,
    'filepath' => '/',
    'filename' => $displayname,
    'userid' => $userid,
);

// Create the course module
$cm = new stdClass();
$cm->course = $courseid;
$cm->module = $DB->get_field('modules', 'id', array('name' => 'resource'));
$cm->section = 0;
$cm->instance = 0;
$cm->name = $displayname;
$cm->visible = 1;
$cm->add = 'resource';

require_once($CFG->dirroot . '/course/modlib.php');
$moduleinfo = new stdClass();
$moduleinfo->course = $courseid;
$moduleinfo->module = $DB->get_field('modules', 'id', array('name' => 'resource'));
$moduleinfo->modulename = 'resource';
$moduleinfo->section = 0;
$moduleinfo->name = $displayname;
$moduleinfo->visible = 1;
$moduleinfo->files = $filepath;

list($cm, $instance) = add_moduleinfo($moduleinfo, $DB->get_record('course', array('id' => $courseid)));

echo json_encode(array('cmid' => $cm->id, 'name' => $displayname, 'course' => $courseid));
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
        schema=GET_MY_COURSES_SCHEMA,
        handler=_handle_get_my_courses,
    )
    ctx.register_tool(
        name="moodle_upload_file",
        schema=UPLOAD_FILE_SCHEMA,
        handler=_handle_upload_file,
    )

    logger.info("moodle-bridge registered: 2 tools")
