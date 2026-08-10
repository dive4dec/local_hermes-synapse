#!/usr/bin/env python3
"""
Moodle Quiz Attempts PDF Downloader (CDP / attach-to-browser tool)

This is the executable backing the `moodle_auto_download` skill. It ATTACHES to
an already-running, already-logged-in Chrome/Chromium instance over the Chrome
DevTools Protocol (CDP) and reuses that browser's live session. It:

  1. Connects to a Chrome DevTools endpoint (--debugger-address host:port) and
     opens a fresh tab in that browser. No login, no username/password — the
     user's existing authenticated session cookies are reused.
  2. Resolves a target course (by numeric course id or by exact course name).
  3. Scans the course page for quiz activities matching keyword filters.
  4. For each matched quiz, opens the "overview" report, reads all finished
     attempts, and selects a stratified sample by grade:
        - HIGH_QUANTITY   top-scoring attempts
        - MEDIUM_QUANTITY attempts nearest the median
        - LOW_QUANTITY    bottom-scoring attempts (zero scores excluded)
  5. Renders each selected attempt's review page to a PDF (Page.printToPDF) and
     saves it into the output directory using the naming convention:
        [Quiz_Name]_[Group]_Rank[Rank]_[User_ID].pdf

Why CDP instead of Selenium+chromedriver?
  chromedriver must version-match the browser. When the controlled browser lives
  on another host (the user's desktop) and updates independently, keeping a
  matching chromedriver in this container is brittle. Raw CDP is a stable
  WebSocket protocol that is version-agnostic, so this tool works regardless of
  the attached browser's major version. It also means credentials never touch
  this script, the command line, or cron config.

Usage:
    python3 moodle_quiz_downloader_tool.py \
        --debugger-address 127.0.0.1:9222 \
        --moodle-url https://xxxxxx \
        --course-identifier "2" \
        --high-quantity 3 --medium-quantity 3 --low-quantity 3

The browser at --debugger-address must already be logged into the Moodle site.
Start it (on the user's machine) with, e.g.:
    chrome --remote-debugging-port=9222
and log into Moodle once. If this container reaches the browser over a network,
tunnel the port so CDP sees a localhost Host header (Chrome rejects non-local
Host headers), e.g. inside the container:
    socat TCP-LISTEN:9222,bind=127.0.0.1,fork TCP:<host>:9222
then pass --debugger-address 127.0.0.1:9222.
"""

import os
import re
import sys
import json
import time
import base64
import shutil
import socket
import argparse
import subprocess
from datetime import datetime
from typing import Dict, List, Optional

try:
    import requests
    import websocket  # websocket-client
    CDP_AVAILABLE = True
except ImportError:
    CDP_AVAILABLE = False


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def sanitize(name: str) -> str:
    """Make a string safe to use inside a filename."""
    name = (name or "quiz").strip()
    name = re.sub(r'[\\/:*?"<>|]+', "_", name)
    name = re.sub(r'\s+', "_", name)
    return name[:80] or "quiz"


# --------------------------------------------------------------------------- #
# Minimal Chrome DevTools Protocol client
# --------------------------------------------------------------------------- #
class CDPSession:
    """
    A tiny synchronous CDP client that attaches to a running browser, opens its
    own tab, and exposes just what this tool needs: navigate, evaluate JS, and
    print-to-PDF. Uses the HTTP /json endpoints to discover targets and a raw
    WebSocket for the protocol. No chromedriver, version-agnostic.
    """

    def __init__(self, debugger_address: str, timeout: int = 60):
        self.debugger_address = debugger_address.strip()
        self.timeout = timeout
        self.ws = None
        self._id = 0
        self.target_id = None      # the tab we created (so we can close it)
        self._own_tab = False
        self._proc = None          # a browser WE launched (server-side mode)

    # -- lifecycle -------------------------------------------------------- #
    def _http_base(self) -> str:
        return f"http://{self.debugger_address}"

    @staticmethod
    def _free_port() -> int:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        return port

    @classmethod
    def launch(cls, timeout: int = 60, user_data_dir: Optional[str] = None, cert_spki_hash: Optional[str] = None):
        """Start a local headless Chromium with a debugging port and return a
        connected CDPSession bound to it. Used server-side so no pre-existing
        browser is needed. The browser is OURS and is killed on close()."""
        binary = (shutil.which("chromium") or shutil.which("chromium-browser")
                  or shutil.which("google-chrome") or shutil.which("chrome"))
        if not binary:
            raise RuntimeError(
                "No Chromium/Chrome binary found on PATH to launch headless.")
        port = cls._free_port()
        if not user_data_dir:
            user_data_dir = f"/tmp/hermes-moodle-cdp-{os.getpid()}-{port}"
        args = [
            binary, "--headless=new", "--no-sandbox", "--disable-gpu",
            "--disable-dev-shm-usage", "--window-size=1920,1080",
            # target Moodle may use a self-signed cert; don't hit the interstitial
            "--ignore-certificate-errors", "--allow-insecure-localhost",
            f"--user-data-dir={user_data_dir}",
            f"--remote-debugging-port={port}", "about:blank",
        ]
        
        if cert_spki_hash:
            args.append(f"--ignore-certificate-errors-spki-list={cert_spki_hash}")

        proc = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self = cls(f"127.0.0.1:{port}", timeout=timeout)
        self._proc = proc
        self._user_data_dir = user_data_dir
        # Wait for the debugging endpoint to come up.
        try:
            deadline = time.time() + 30
            while time.time() < deadline:
                try:
                    requests.get(f"http://127.0.0.1:{port}/json/version", timeout=2)
                    break
                except Exception:
                    if proc.poll() is not None:
                        raise RuntimeError("Launched browser exited before ready.")
                    time.sleep(0.4)
            else:
                raise RuntimeError("Launched browser never opened its debug port.")
            return self.connect()
        except Exception as e:
            log(f"!! Browser launch or connection failed: {e}. Cleaning up spawned process...")
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass

            if user_data_dir and os.path.exists(user_data_dir) and user_data_dir.startswith("/tmp/"):
                shutil.rmtree(user_data_dir, ignore_errors=True)

            raise

    def connect(self):
        """Verify the endpoint, open a fresh tab, and attach a WebSocket to it."""
        base = self._http_base()
        # 1) Sanity check the endpoint and surface a helpful browser version.
        try:
            ver = requests.get(f"{base}/json/version", timeout=10).json()
            log(f"Connected to browser: {ver.get('Browser', '?')}")
        except Exception as e:
            raise RuntimeError(
                f"Could not reach a Chrome DevTools endpoint at "
                f"{self.debugger_address}: {e}\n"
                f"  - Is the browser running with --remote-debugging-port?\n"
                f"  - If it's on another host, tunnel it so the Host header is "
                f"localhost, e.g.: socat TCP-LISTEN:{self._port()},bind=127.0.0.1,"
                f"fork TCP:<host>:<port>"
            )

        # 2) Open our own tab so we never disturb the user's current tab.
        ws_url = self._open_new_tab(base)

        # 3) Attach the WebSocket.
        # suppress_origin: modern Chrome rejects the DevTools WebSocket handshake
        # when the Origin header doesn't match an allow-list (403 Forbidden with
        # "Use --remote-allow-origins"). Chrome permits handshakes that carry NO
        # Origin header, so we suppress it — this avoids forcing the user to add
        # --remote-allow-origins when launching their browser.
        self.ws = websocket.create_connection(
            ws_url, max_size=None, timeout=self.timeout, suppress_origin=True
        )
        # Enable the domains we use.
        self.send("Page.enable")
        self.send("Runtime.enable")
        return self

    def _port(self) -> str:
        return self.debugger_address.rsplit(":", 1)[-1]

    def _open_new_tab(self, base: str) -> str:
        """Create a new about:blank tab and return its webSocketDebuggerUrl."""
        # Newer Chrome requires PUT for /json/new; older accepts GET. Try both.
        info = None
        for method in ("put", "get"):
            try:
                resp = getattr(requests, method)(
                    f"{base}/json/new?about:blank", timeout=10
                )
                if resp.ok:
                    info = resp.json()
                    break
            except Exception:
                continue
        if info and info.get("webSocketDebuggerUrl"):
            self.target_id = info.get("id")
            self._own_tab = True
            return info["webSocketDebuggerUrl"]

        # Fallback: attach to the first existing page target (do NOT close it).
        log("  Could not open a new tab; attaching to an existing page tab.")
        pages = requests.get(f"{base}/json", timeout=10).json()
        for t in pages:
            if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                self.target_id = t.get("id")
                self._own_tab = False
                return t["webSocketDebuggerUrl"]
        raise RuntimeError("No attachable page target found in the browser.")

    def close(self):
        """Close our WebSocket and, if we created the tab, close that tab too.
        If we LAUNCHED the browser (server-side mode), kill it and clean its
        profile dir. Never quits a browser we merely attached to."""
        try:
            if self.ws is not None:
                self.ws.close()
        except Exception:
            pass
        self.ws = None
        if self._own_tab and self.target_id and self._proc is None:
            # Only bother closing the tab when attached to someone else's browser;
            # a browser we launched is about to be killed wholesale anyway.
            try:
                requests.get(
                    f"{self._http_base()}/json/close/{self.target_id}", timeout=10
                )
            except Exception:
                pass
        self.target_id = None
        # Tear down a browser we started ourselves.
        if self._proc is not None:
            try:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=5)
                except Exception:
                    self._proc.kill()
            except Exception:
                pass
            self._proc = None
            udd = getattr(self, "_user_data_dir", None)
            if udd and udd.startswith("/tmp/"):
                shutil.rmtree(udd, ignore_errors=True)

    # -- raw protocol ----------------------------------------------------- #
    def send(self, method: str, params: Optional[dict] = None, timeout: Optional[int] = None):
        """Send a CDP command and block for its matching result."""
        self._id += 1
        msg_id = self._id
        payload = {"id": msg_id, "method": method, "params": params or {}}
        self.ws.send(json.dumps(payload))
        deadline = time.time() + (timeout or self.timeout)
        while time.time() < deadline:
            self.ws.settimeout(max(1, deadline - time.time()))
            try:
                raw = self.ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            if not raw:
                continue
            data = json.loads(raw)
            if data.get("id") == msg_id:
                if "error" in data:
                    raise RuntimeError(f"CDP {method} error: {data['error']}")
                return data.get("result", {})
            # else: an event or another response — ignore and keep reading.
        raise RuntimeError(f"CDP {method} timed out after {timeout or self.timeout}s")

    # -- high-level ops --------------------------------------------------- #
    def set_cookie(self, name: str, value: str, domain: str, path: str = "/",
                   secure: bool = True) -> None:
        """Inject a cookie into the browser so subsequent navigations are
        authenticated as that session (used to mirror a user's Moodle login)."""
        self.send("Network.enable")
        params = {
            "name": name,
            "value": value,
            "domain": domain,
            "path": path or "/",
            "secure": bool(secure),
            "httpOnly": True,
        }
        self.send("Network.setCookie", params)

    def navigate(self, url: str, wait: float = 2.0, ready_timeout: int = 30):
        """Navigate the tab and wait until document.readyState == 'complete'."""
        result = self.send("Page.navigate", {"url": url})
        
        if result and "errorText" in result:
            raise RuntimeError(f"Network error when navigating to {url}: {result['errorText']}")

        deadline = time.time() + ready_timeout
        while time.time() < deadline:
            try:
                state = self.evaluate("document.readyState") or ""
                if state == "complete":
                    break
            except Exception:
                pass
            time.sleep(0.3)
            
        current_url = self.evaluate("location.href") or ""
        if current_url.startswith("chrome-error://"):
            raise RuntimeError(f"Browser failed to load the page. URL '{url}' is unreachable.")

        if wait:
            time.sleep(wait)

    def evaluate(self, expression: str):
        """Run JS in the page and return the (JSON-serialisable) value."""
        result = self.send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        })
        res = result.get("result", {})
        return res.get("value")

    def current_url(self) -> str:
        return self.evaluate("location.href") or ""

    def body_text(self) -> str:
        return self.evaluate("document.body ? document.body.innerText : ''") or ""

    def print_to_pdf(self, params: dict) -> bytes:
        result = self.send("Page.printToPDF", params, timeout=120)
        return base64.b64decode(result["data"])


# --------------------------------------------------------------------------- #
# Main downloader
# --------------------------------------------------------------------------- #
class MoodleQuizDownloader:
    def __init__(self, moodle_url: str, output_dir: str,
                 debugger_address: Optional[str] = None,
                 session: Optional[dict] = None,
                 cert_spki_hash: Optional[str] = None):
        """Two modes:
          - attach: pass debugger_address, connect to a running logged-in browser.
          - server-side: pass `session` (parsed msession file); launch a local
            headless browser and inject the user's Moodle cookie into it.
        `session` takes precedence when both are given.
        """
        self.moodle_url = moodle_url.rstrip('/')
        if self.moodle_url.startswith("http://"):
            raise ValueError(
                f"Insecure connection blocked: '{self.moodle_url}' uses unencrypted HTTP. "
                "Must use HTTPS to prevent session cookie interception."
            )
        self.debugger_address = debugger_address
        self.session = session
        self.output_dir = output_dir
        self.cert_spki_hash = cert_spki_hash
        self.cdp: Optional[CDPSession] = None

    # -- browser lifecycle ------------------------------------------------ #
    def _ensure_session(self) -> CDPSession:
        if self.cdp is None:
            if not CDP_AVAILABLE:
                raise RuntimeError(
                    "Missing deps: requests and websocket-client. "
                    "Run: pip install -r requirements.txt")
            if self.session:
                # Server-side mode: launch our own headless browser and inject
                # the user's live Moodle session cookie so it acts as that user.
                self.cdp = CDPSession.launch(cert_spki_hash=self.cert_spki_hash)
                self.cdp.set_cookie(
                    name=self.session["cookie_name"],
                    value=self.session["cookie_value"],
                    domain=self.session["domain"],
                    path=self.session.get("path", "/"),
                    secure=self.session.get("secure", True),
                )
                log("Injected the requesting user's Moodle session into the "
                    "headless browser.")
            else:
                # Attach mode: connect to a pre-existing logged-in browser.
                self.cdp = CDPSession(self.debugger_address).connect()
        return self.cdp

    def quit(self):
        if self.cdp is not None:
            # Closes our tab (attach) or kills the browser we launched (server-side);
            # never quits a browser we merely attached to.
            self.cdp.close()
            self.cdp = None

    # -- session check ---------------------------------------------------- #
    def verify_logged_in(self) -> None:
        """The browser session must be authenticated. Detect the login page and
        fail with a clear, mode-appropriate message instead of scraping nothing."""
        c = self._ensure_session()
        c.navigate(f"{self.moodle_url}/my/", wait=1.5)
        url = c.current_url()
        if "login/index.php" in url:
            if self.session:
                raise RuntimeError(
                    "Injected Moodle session is not valid (redirected to "
                    f"{url}). The user's session cookie may have expired or the "
                    "domain/path didn't match. Ask the user to reload the Moodle "
                    "chat (which refreshes their session file), then retry.")
            raise RuntimeError(
                "The attached browser is NOT logged into Moodle "
                f"(redirected to {url}). Log into {self.moodle_url} in that "
                "browser first, then re-run.")
        who = ("the session-injected user" if self.session
               else "the existing browser session")
        log(f"Authenticated as {who} ({url}).")

    # -- course resolution ------------------------------------------------ #
    def resolve_course_url(self, course_identifier: str) -> str:
        """Return a course view URL from either a numeric id or a course name."""
        c = self._ensure_session()
        if re.fullmatch(r"\d+", course_identifier.strip()):
            return f"{self.moodle_url}/course/view.php?id={course_identifier.strip()}"

        # Treat as a course name: search and pick the first match.
        log(f"Resolving course by name: '{course_identifier}'")
        c.navigate(
            f"{self.moodle_url}/course/search.php?search={course_identifier}",
            wait=2,
        )
        # Collect candidate course links (specific selector first, then any).
        js = """
        (function(){
          var out=[];
          var sel=document.querySelectorAll("ul.courses li.course a[href*='course/view.php']");
          if(!sel.length){sel=document.querySelectorAll("a[href*='course/view.php']");}
          sel.forEach(function(a){out.push({href:a.href,text:(a.innerText||'').trim()});});
          return out;
        })()
        """
        links = c.evaluate(js) or []
        for link in links:
            if course_identifier.lower() in (link.get("text") or "").lower():
                return link["href"]
        if links:
            return links[0]["href"]
        raise RuntimeError(
            f"Could not resolve a course for identifier '{course_identifier}'."
        )

    # -- quiz discovery --------------------------------------------------- #
    def find_quizzes(self, course_url: str, keywords: List[str],
                     exact: bool = False) -> List[Dict]:
        """
        Scan the course page for quiz activities matching the keywords.

        exact=False (default): a quiz matches if any keyword is a substring of
            its name (case-insensitive). e.g. "iRAT" matches "iRAT1", "iRAT10".
        exact=True: a quiz matches only if its name equals one of the keywords
            exactly (case-insensitive, surrounding whitespace stripped). Use this
            to target "iRAT1" without also catching "iRAT10".
        """
        c = self._ensure_session()
        log(f"Scanning course page for quizzes: {course_url}")
        c.navigate(course_url, wait=2)

        js = """
        (function(){
          var out=[];
          document.querySelectorAll("a[href*='mod/quiz/view.php']").forEach(function(a){
            out.push({href:a.href,text:(a.innerText||'').trim()});
          });
          return out;
        })()
        """
        quiz_links = c.evaluate(js) or []
        results = []
        seen = set()
        for link in quiz_links:
            text = (link.get("text") or "").strip()
            href = link.get("href") or ""
            if not text or "mod/quiz/view.php" not in href:
                continue
            m = re.search(r"[?&]id=(\d+)", href)
            if not m:
                continue
            cmid = m.group(1)
            if cmid in seen:
                continue
            if keywords:
                if exact:
                    if text.lower() not in [k.lower().strip() for k in keywords]:
                        continue
                else:
                    if not any(k.lower() in text.lower() for k in keywords):
                        continue
            seen.add(cmid)
            results.append({"cmid": cmid, "name": text, "url": href})
        log(f"Found {len(results)} matching quiz(es).")
        return results

    # -- attempt extraction ----------------------------------------------- #
    def get_attempts(self, quiz: Dict) -> List[Dict]:
        c = self._ensure_session()
        cmid = quiz["cmid"]
        base = (
            f"{self.moodle_url}/mod/quiz/report.php?id={cmid}"
            f"&mode=overview&attempts=all_with"
        )
        log(f"  Reading attempts for quiz '{quiz['name']}'")

        # 1. 修复 JS 脚本：在抓取 review 链接时，同时寻找同一行 (tr) 的 user 链接
        collect_js = """
        (function(){
          var out=[];
          document.querySelectorAll("a[href*='review.php?attempt=']").forEach(function(a){
            var uid = "";
            var tr = a.closest("tr");
            if(tr){
              var ulink = tr.querySelector("a[href*='user/view.php']");
              if(ulink){
                var m = ulink.href.match(/[?&]id=(\d+)/);
                if(m) uid = m[1];
              }
            }
            out.push({href: a.href, user_id: uid});
          });
          return out;
        })()
        """

        attempt_links: dict = {}  # attempt_id -> {"href": url, "user_id": uid}
        page = 1
        while True:
            url = f"{base}&pagesize=100000&page={page}"
            c.navigate(url, wait=2.5)
            before = len(attempt_links)
            
            # 2. 接收 JS 返回的对象数组，安全保存 user_id
            for item in (c.evaluate(collect_js) or []):
                href = item.get("href", "")
                uid = item.get("user_id", "")
                m = re.search(r"attempt=(\d+)", href)
                if m:
                    attempt_links.setdefault(m.group(1), {"href": href, "user_id": uid})
                    
            added = len(attempt_links) - before
            if added == 0 and page > 1:
                break
            page += 1
            if page > 50:
                break

        if not attempt_links:
            c.navigate(f"{base}&pagesize=100000", wait=2.5)
            for item in (c.evaluate(collect_js) or []):
                href = item.get("href", "")
                uid = item.get("user_id", "")
                m = re.search(r"attempt=(\d+)", href)
                if m:
                    attempt_links.setdefault(m.group(1), {"href": href, "user_id": uid})

        log(f"  Found {len(attempt_links)} distinct attempt(s); reading each grade...")

        attempts = []
        # 3. 直接使用抓取到的 user_id，彻底废弃错误的正则匹配
        for attempt_id, data in attempt_links.items():
            href = data["href"]
            user_id = data["user_id"]
            
            grade = self._read_attempt_grade(href)
            if grade is None:
                continue
                
            attempts.append({
                "attempt_id": attempt_id,
                "user_id": user_id,
                "grade": grade,
                "review_url": href,
            })

        attempts.sort(key=lambda a: a["grade"], reverse=True)
        log(f"  Parsed {len(attempts)} finished attempt(s).")
        return attempts

    @staticmethod
    def _parse_grade_from_text(body: str):
        """Return the attempt grade normalized to a percentage-of-max (float),
        or None if it cannot be read.

        Moodle can be configured to display grades three ways; all are handled
        and normalized to "percent of max grade" so sampling is consistent:
          - Fraction:    "Grade: 10.00 / 10.00"  -> 100.0
          - 'out of':    "Grade 8 out of 10"      -> 80.0
          - Percentage:  "Grade: 100%"            -> 100.0
        The Percentage form previously fell through to 0.0, which made full-mark
        (满分) attempts look like zero scores and get excluded from the High
        sample even though only genuine zero scores should be skipped.
        """
        if not body:
            return None
        # 1) Fraction form "X / Y" attached to the Grade label.
        m = re.search(r"grade\s*[:/]?\s*([\d.]+)\s*/\s*([\d.]+)", body,
                      re.IGNORECASE)
        if m:
            num, den = float(m.group(1)), float(m.group(2))
            return (num / den * 100.0) if den else 0.0
        # 2) Percentage form "X%" attached to the Grade label. This value is
        #    already a percentage of the max grade, so return it as-is.
        mp = re.search(r"grade\s*[:/]?\s*([\d.]+)\s*%", body, re.IGNORECASE)
        if mp:
            return float(mp.group(1))
        # 3) "X out of Y" form.
        mo = re.search(r"grade\s*[:/]?\s*([\d.]+)\s*out of\s*([\d.]+)", body,
                       re.IGNORECASE)
        if mo:
            num, den = float(mo.group(1)), float(mo.group(2))
            return (num / den * 100.0) if den else 0.0

        return None

    def _read_attempt_grade(self, review_url: str):
        """Open a review page and return the authoritative grade (float,
        normalized to a percentage of the max grade), or None if the attempt is
        not Finished or its grade cannot be read."""
        c = self._ensure_session()
        for _ in range(2):  # one retry for transient navigation issues
            try:
                c.navigate(review_url, wait=1.2)
                body = c.body_text()
                # Must be a finished attempt.
                if "in progress" in body.lower() and "finished" not in body.lower():
                    return None
                return self._parse_grade_from_text(body)
            except Exception as e:
                log(f"!! grade read failed: {e}")
                time.sleep(1.5)
        return None

    # -- stratified sampling --------------------------------------------- #
    @staticmethod
    def sample(attempts: List[Dict], high: int, medium: int, low: int) -> List[Dict]:
        """Return a deduplicated, tagged list of selected attempts."""

        if not attempts:
            return []

        # 1. 在分配排名和分段前，按 user_id 去重（保留最高分）
        # 由于传入的 attempts 已经按 grade 降序排列，第一次遇到的 user_id 就是其最高分
        unique_attempts = []
        seen_users = set()
        for a in attempts:
            uid = a.get("user_id")
            if uid:
                if uid in seen_users:
                    continue  # 跳过该学生的低分尝试
                seen_users.add(uid)
            unique_attempts.append(a)
            
        # 使用去重后的、真正代表每个学生最高分的数据集覆盖原列表
        attempts = unique_attempts

        # 2. 重新计算全局排名
        for i, a in enumerate(attempts, start=1):
            a["global_rank"] = i

        selected: List[Dict] = []
        taken_ids = set()

        def take(group_list, group_name):
            for a in group_list:
                # 这里的 attempt_id 去重依然保留，作为安全兜底
                if a["attempt_id"] in taken_ids:
                    continue
                taken_ids.add(a["attempt_id"])
                selected.append({**a, "group": group_name, "rank": a["global_rank"]})

        # 3. 执行分层抽样
        nz = [a for a in attempts if a["grade"] > 0]

        if high > 0 and nz:
            high_n = max(0, min(high, len(nz)))
            take(nz[:high_n], "High")

        if low > 0 and nz:
            low_n = max(0, min(low, len(nz)))
            take(nz[-low_n:][::-1], "Low")

        if medium > 0 and len(attempts) > 0:
            # 此时的 len(attempts) 是准确的实际学生人数，中位数计算也会恢复准确
            start = max(0, (len(attempts) - medium) // 2)
            end = min(len(attempts), start + medium)
            take(attempts[start:end], "Medium")

        return selected

    # -- PDF download ----------------------------------------------------- #
    def download_pdfs(self, quiz: Dict, selected: List[Dict]) -> List[str]:
        c = self._ensure_session()
        saved = []
        for a in selected:
            attempt_id = a["attempt_id"]
            log(f"  Downloading {a['group']} attempt {attempt_id} "
                f"(user {a['user_id'] or '?'}).")
            try:
                c.navigate(a["review_url"], wait=2)
                pdf = c.print_to_pdf({
                    "printBackground": True,
                    "landscape": False,
                    "displayHeaderFooter": False,
                    "preferCSSPageSize": True,
                    "scale": 0.9,
                })
                fname = (
                    f"{sanitize(quiz['name'])}_{a['group']}_"
                    f"Rank{a['rank']}_{a['user_id'] or attempt_id}.pdf"
                )
                fpath = os.path.join(self.output_dir, fname)
                with open(fpath, "wb") as f:
                    f.write(pdf)
                saved.append(fpath)
                log(f"    -> saved {fname}")
            except Exception as e:
                log(f"    !! failed to download attempt {attempt_id}: {e}")
        return saved

    # -- orchestration ---------------------------------------------------- #
    def run(self, course_identifier: str, high: int, medium: int, low: int,
            keywords: List[str], download: bool, exact: bool = False) -> Dict:
        os.makedirs(self.output_dir, exist_ok=True)
        summary: Dict[str, Dict] = {}
        try:
            self.verify_logged_in()
            course_url = self.resolve_course_url(course_identifier)
            quizzes = self.find_quizzes(course_url, keywords, exact=exact)
            for quiz in quizzes:
                attempts = self.get_attempts(quiz)
                selected = self.sample(attempts, high, medium, low)
                summary[quiz["name"]] = {
                    "cmid": quiz["cmid"],
                    "total_attempts": len(attempts),
                    "selected": [
                        {k: s[k] for k in ("attempt_id", "user_id", "grade",
                                           "group", "rank")}
                        for s in selected
                    ],
                }
                if download and selected:
                    self.download_pdfs(quiz, selected)
        finally:
            self.quit()
        return summary


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _load_session_file(path: str, ttl: int, expected_userid: Optional[int] = None) -> dict:
    """Load and validate a per-user msession JSON written by the Moodle plugin.
    Enforces a TTL so a stale session secret can't be reused indefinitely.
    If expected_userid is given, the file's userid must match — prevents a
    caller from loading another user's session file."""
    if not os.path.exists(path):
        raise RuntimeError(
            f"Session file not found: {path}. The Moodle plugin writes it per "
            f"user on each chat request; make sure the user has an active "
            f"Moodle session and has sent a message.")
    with open(path) as f:
        data = json.load(f)
    for k in ("cookie_name", "cookie_value", "domain"):
        if not data.get(k):
            raise RuntimeError(f"Session file {path} is missing '{k}'.")
    # Validate userid if the file carries one and we have an expected value.
    file_uid = data.get("userid")
    if expected_userid is not None and file_uid is not None:
        if int(file_uid) != int(expected_userid):
            raise RuntimeError(
                f"Session file {path} belongs to user {file_uid}, "
                f"but expected user {expected_userid}. Session hijack blocked.")
    age = time.time() - int(data.get("written_at", 0))
    if ttl > 0 and age > ttl:
        raise RuntimeError(
            f"Session file {path} is stale ({int(age)}s old > {ttl}s TTL). "
            f"Ask the user to send a fresh message in the Moodle chat, then retry.")
    return data


def _resolve_session(args) -> Optional[dict]:
    """Return a parsed session dict for server-side mode, or None for attach mode.
    The requesting user's id comes from $HERMES_HOME/.moodle_identity (written
    by the bridge on each request), NOT from CLI args — prevents the agent from
    impersonating another user."""
    # Read the trusted identity file written by the bridge per-request.
    expected_uid = None
    identity_file = os.environ.get("HERMES_HOME", "/var/www/moodledata/.hermes")
    identity_path = os.path.join(identity_file, ".moodle_identity")
    if os.path.exists(identity_path):
        try:
            with open(identity_path) as f:
                ident = json.load(f)
            expected_uid = ident.get("userid")
        except Exception:
            pass  # degrade gracefully if file is unreadable

    if args.session_file:
        return _load_session_file(args.session_file, args.session_ttl,
                                  expected_uid)
    if expected_uid:
        path = os.path.join(identity_file, "run", f"msession.json")
        return _load_session_file(path, args.session_ttl, expected_uid)
    return None


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Download Moodle quiz attempts as PDFs based on score "
                    "rankings. Server-side mode (default for the Moodle plugin): "
                    "launch a headless browser and inject the requesting user's "
                    "Moodle session from the bridge's .moodle_identity file — zero "
                    "user action, no password. Attach mode: connect to an "
                    "already-logged-in browser via --debugger-address. Either "
                    "way, no chromedriver and no credentials in the command.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    # Server-side (session-injection) mode — preferred in the multi-user plugin.
    p.add_argument("--session-file", default="",
                   help="Explicit path to a msession JSON file (overrides "
                        "auto-resolved path from .moodle_identity).")
    p.add_argument("--session-ttl", type=int, default=1800,
                   help="Max age in seconds a session file may be before it is "
                        "rejected as stale (0 disables the check).")
    # Attach mode — connect to a browser the user already opened & logged into.
    p.add_argument("--debugger-address", default="",
                   help="host:port of a Chrome DevTools endpoint of an "
                        "already-running, already-logged-in browser (attach mode).")
    p.add_argument("--moodle-url", required=True, help="Moodle base URL")
    p.add_argument("--course-identifier", required=True,
                   help="Target course ID (e.g. '2') or exact course name")
    p.add_argument("--high-quantity", type=int, default=3,
                   help="Number of top-scoring attempts to download")
    p.add_argument("--medium-quantity", type=int, default=3,
                   help="Number of median-scoring attempts to download")
    p.add_argument("--low-quantity", type=int, default=3,
                   help="Number of bottom-scoring attempts to download "
                        "(zero scores excluded)")
    p.add_argument("--keywords", default="",
                   help="Comma-separated keywords to filter quizzes by name. "
                        "Empty (default) = scan ALL quizzes in the course, "
                        "regardless of name. Use this when quiz names do not "
                        "contain words like 'Test' or 'Quiz'.")
    p.add_argument("--exact-quiz-name", action="store_true",
                   help="Match quiz names exactly (case-insensitive) instead of "
                        "as a substring. Use to target 'iRAT1' without also "
                        "matching 'iRAT10'. Requires --keywords to list the exact "
                        "quiz name(s).")
    p.add_argument("--output-dir", default="/var/www/moodledata/.hermes/cron/output/",
                   help="Directory to save PDFs into")
    p.add_argument("--no-download", action="store_true",
                   help="Only print the selected sample; do not render PDFs")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if not CDP_AVAILABLE:
        print("ERROR: missing deps 'requests' and/or 'websocket-client'. Run: "
              "pip install -r requirements.txt", file=sys.stderr)
        return 2

    # Resolve mode: server-side session injection vs attach to a running browser.
    try:
        session = _resolve_session(args)
    except Exception as e:
        log(f"FATAL: {e}")
        return 1
    if not session and not args.debugger_address:
        log("FATAL: no session source. Ensure $HERMES_HOME/.moodle_identity "
            "exists (written by the bridge) or pass --debugger-address (attach mode).")
        return 1

    # Empty keywords => match ALL quizzes (no name filtering). This is the
    # default so the tool never silently skips a quiz whose name lacks
    # "Test"/"Quiz". To filter, the agent passes e.g. --keywords "Test,Quiz".
    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    downloader = MoodleQuizDownloader(
        moodle_url=args.moodle_url,
        output_dir=args.output_dir,
        debugger_address=args.debugger_address or None,
        session=session,
    )

    mode = "server-side session-inject" if session else "CDP attach"
    log(f"Starting Moodle quiz downloader ({mode} mode)")
    try:
        summary = downloader.run(
            course_identifier=args.course_identifier,
            high=args.high_quantity,
            medium=args.medium_quantity,
            low=args.low_quantity,
            keywords=keywords,
            download=not args.no_download,
            exact=args.exact_quiz_name,
        )
    except Exception as e:
        log(f"FATAL: {e}")
        return 1

    print("\n" + "=" * 60)
    print("SELECTION SUMMARY")
    print("=" * 60)
    total_selected = 0
    for quiz_name, info in summary.items():
        print(f"\nQuiz: {quiz_name} (cmid={info['cmid']})")
        print(f"  Total attempts parsed: {info['total_attempts']}")
        for s in info["selected"]:
            print(f"  - [{s['group']}] rank {s['rank']} | attempt "
                  f"{s['attempt_id']} | user {s['user_id'] or '?'} | "
                  f"grade {s['grade']}")
            total_selected += 1
    print(f"\nTotal selected attempts: {total_selected}")
    print(f"Output directory: {os.path.abspath(args.output_dir)}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
