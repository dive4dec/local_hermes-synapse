---
name: moodle-forum-management
description: "Manage Moodle forum content: resolve forum URLs, copy discussions/posts between forums (e.g. FAQ sync between cloned courses), and verify a discussion actually renders in the listing. Verified recipe from 2026-08-23."
---

# Moodle Forum Content Management

Read, copy, and verify forum discussions/posts on dive.cs.cityu.edu.hk (Moodle 5.x). Primary use case: syncing FAQ-style posts between the parallel CS1302 courses (cs1302a_26a=3 and cs1302_26a=7), which each have their own CE-Quiz FAQ / Project FAQ forums that must be kept in sync when a course is cloned.

## Triggers

- "Copy this post/discussion to the other course's forum"
- Checking what a `mod/forum/discuss.php?d=N#pM` URL contains
- Verifying a forum change is visible in the UI listing (not just DB state)
- Any forum content maintenance between the parallel courses

## Tool landscape (current)

- **Reads:** `mcp__moodle_db__query` MCP tool (see `moodle-mcp-db-query` skill — mind its keyword filter: column names containing `created`/`deleted`/`timecreated` get rejected).
- **Writes:** PHP bootstrap scripts (see `moodle-db-access` skill). Note: that skill's "no general query tool exists" section is **outdated** — the MCP query tool exists and works; only its write guidance is authoritative.
- **Note:** `moodle-db-access` and `moodle-add-activity-via-db` are manually authored skills — do not patch them from curation passes; put forum-specific learnings here.

## Resolving a forum URL

`mod/forum/discuss.php?d=N#pM` → `N` = `mdl_forum_discussions.id`, `M` = `mdl_forum_posts.id`.

```sql
-- discussion + title + author
SELECT d.id, d.forum, d.name, d.userid, d.firstpost, d.timemodified,
       f.name AS forumname, f.course
FROM mdl_forum_discussions d
JOIN mdl_forum f ON f.id = d.forum WHERE d.id = N;

-- all posts in the discussion (skip `created`/`deleted` columns — keyword filter)
SELECT p.id, p.userid, p.subject, p.message, p.messageformat, p.messagetrust,
       u.firstname, u.lastname, u.email
FROM mdl_forum_posts p JOIN mdl_user u ON u.id = p.userid
WHERE p.discussion = N ORDER BY p.id;
```

Schema quirks: `mdl_forum_discussions.forum` (not `forumid`), `.name` is the title (no `subject` column); `mdl_forum_posts.discussion` (not `discussionid`), replies link via `.parent`; **`messageformat` in THIS build (Moodle 5.x, verified 2026-10-13): `0` = Moodle markdown (FORMAT_MOODLE), `1` = HTML, `2` = plain** — the old "format 4 = Moodle markdown" note is pre-renumbering and WRONG here (a post stored with `messageformat=0` renders `**bold**` / markdown correctly; do not "fix" it to 4).

## Copying a discussion+post to another forum (verified 2026-08-23)

PHP bootstrap + `$DB->insert_record()`:

1. Read source discussion + `$DB->get_records('forum_posts', ['discussion' => $srcid, 'deleted' => 0])`. Sanity-check: for a single-post FAQ, exactly 1 root post and `d.firstpost` == that post's id.
2. Insert `forum_discussions`: `course, forum (target), name, firstpost=0, userid, groupid (copy from source; -1 = all users), assessed=1, timemodified=time(), usermodified=$author, timestart=0, timeend=0, pinned=0, timelocked=0`.
3. Insert `forum_posts`: `discussion=$newdiscid, parent=0, userid, created=time(), modified=time(), mailed=0, subject, message, messageformat, messagetrust, attachment, totalscore=0, mailnow=0, deleted=0, privatereplyto=0`. Copy `message`/`messageformat`/`messagetrust` byte-for-byte (markdown `<kbd>`, bold etc. carry over fine).
4. `$DB->set_field('forum_discussions', 'firstpost', $newpostid, ['id' => $newdiscid])` — **mandatory**; with `firstpost=0` the discussion is silently absent from the listing.
5. Round-trip verify in the same script: re-fetch discussion + its firstpost post, compare `message` string-identical to source; print both new ids and the resulting URL (`/mod/forum/discuss.php?d=$newdiscid`).
6. `cd /var/www/html/public && moosh -n cache-clear` (site rule: after every DB write).

## Creating a NEW announcement in a `news` forum (verified 2026-10-13)

When the ask is "make an announcement" (not "copy this post"), post a brand-new discussion into the course **Announcements** `news` forum. Same two-table insert as the copy recipe, but authored fresh:

1. **Pick the right news forum + CM.** There are several same-named "Announcements" forums on course 3 (cmids 103, 196, 201, 667 — the live one is cmid **103**, section 19, `type=news`, forum id **2**). Confirm with recent-post recency / which CM is on the main course page.
2. Insert `forum_discussions`: `course, forum=<forumid>, name=<title>, userid=<author>, groupid=0, assessed=1, timemodified=time(), usermodified=<author>, timestart=time(), timeend=0, pinned=0, timelocked=0, firstpost=0`.
3. Insert `forum_posts`: `discussion=<newdiscid>, parent=0, userid, created=time(), modified=0, mailed=0, subject=<title> (SAME as the discussion name — REQUIRED), message=<body>, messageformat=FORMAT_MOODLE (==0 here), messagetrust=1` (teacher-authored = trusted), `attachment='', totalscore=0, mailnow=0, deleted=0`.
   ⚠️ **The post's `subject` must be populated, not `''`** (user correction 2026-10-13: a post created with `subject=''` was reported as "missing the required subject field" and needed a follow-up `set_field` fix). A news-forum post carries the title in BOTH `forum_discussions.name` AND `forum_posts.subject`.
4. `$DB->set_field('forum_discussions','firstpost',$postid,['id'=>$discid])` — mandatory, same as copy.
5. Trigger `\mod_forum\event\discussion_created` (nice-to-have; wrap in try/catch — the DB rows are what matter). **Do NOT call `cache_helper::purge_by_criteria(...)` — that method does not exist in this build** (fatals `Call to undefined method core_cache\helper::purge_by_criteria()`). Just `moosh -n cache-clear`.
6. Verify via the page-SQL join in the "Verifying" section (it's the top post). Note: in this build **`mdl_forum_discussions` has NO `coursemodules`/`numreplies`/`sawall`/`subscription`/`timecreated`/`timemodified2` columns** — do not insert them.
7. Flag to the user that other same-named "Announcements" forums exist and offer to mirror if wanted.

Author: on course 3 the instructor is **user 494 (Chung Chan, chung.chan@cityu.edu.hk)** — not user 2 (that's a different site-admin identity used for old FAQ posts). Use 494 for his announcements so they're in his name.

## Verifying the discussion renders in the listing (the trap)

**Do NOT verify with `forum_get_discussions()` from a minimal CLI bootstrap.** Signature is `forum_get_discussions($cm, ...)` — it takes a **course_module**, not a forum record, and returns `[]` when `has_capability('mod/forum:viewdiscussion', $modcontext)` fails (no logged-in `$USER` in a bare bootstrap). Passing a forum row yields 0 rows, which looks like "not visible" but is a test artifact. (`login_as()` was not found in non-test code as of 2026-08-23 — re-check by code search before relying on either way.)

**Reliable check = the page's own SQL** (from `mod/forum/lib.php::forum_get_discussions()`, ~line 1724), run read-only via the MCP tool:

```sql
SELECT d.id, d.name, d.firstpost, p.id AS postid, p.userid
FROM mdl_forum_discussions d
JOIN mdl_forum_posts p ON p.discussion = d.id
WHERE d.forum = <forumid> AND p.parent = 0
ORDER BY d.id;
```

New discussion present ⇒ it renders. Group mode is the only extra filter on top of this join: check `mdl_course_modules.groupmode`/`groupingid` for the forum's CM; with `groupmode = 0` the join result is exactly what the UI shows. This satisfies the user's "verify what the UI shows, not just DB state" bar without a web session.

## Checking which student posts need a reply ("anything I should answer in the forums?")

Recurring user request: review all course forums and surface student posts with no staff reply. Verified 2026-09-05 on cs1302a_26a (course 3).

1. List forums: `SELECT id, name, type FROM mdl_forum WHERE course = <cid>` — types: `news` (announcements, no reply workflow), `general`, `qanda` (live Q&A), `qa` (obsolete clone dregs).
2. Use the **PHP bootstrap** (the MCP query tool is blocked here: post `deleted`/`created` columns trip the keyword filter) and **always log in**: `global $USER; $USER = get_admin();` — a bare bootstrap hit swallowed "Error reading from database" on forum queries 2026-09-05.
3. **Staff set** = users with a course-level (contextlevel 50, instanceid=cid) role assignment `shortname != 'student'`, **PLUS site admins** — the site admin (user 2 "Admin User" here) typically has NO course role assignment; forgetting them makes the admin's own welcome post/discussion look like an unanswered "student post" (false positive observed 2026-09-05).
4. Per discussion: `$DB->get_records('forum_posts', ['discussion' => $d->id, 'deleted' => 0], 'created ASC')`, scan in order — track the last student post and whether any staff post follows it.
5. Classify before flagging (all of these trip a naive "no staff reply after last student post" check but need no reply):
   - Staff-started discussion threads (the user opened it; only flag if a *student question* is the final post).
   - `qanda` forum entries whose **starter is staff** — these are published FAQ answers, not student questions; "UNANSWERED" there means "nobody replied to your FAQ", not "a student is waiting".
   - Student-to-student threads (project group-mate finding, peer answers) — list them as "no teacher reply needed".
   - `news` forums — never flag.
6. For each genuinely flagged thread print the latest student post (`strip_tags`, squash whitespace, ~250 chars) so the user can decide without opening Moodle; give a one-line status for everything else.
7. Also report dead duplicate forums while you're there (course 3 has three empty `qa`-type "CE-Quiz FAQ" forums, ids 7/8/10, beside the live `qanda` id 11) — the user may want them archived/deleted.

## Pitfalls

- Multiple forums with the same name exist (cs1302a_26a has four "CE-Quiz FAQ" forums — ids 7, 8, 10, 11 — from clones). Always disambiguate by listing `mdl_forum WHERE course = <id>` and matching `type` (the live one is `qanda`, the dead clones are `qa`) and by which one the URL's CM points to.
- **`mdl_forum_discussions` has NO `created` column** — `$DB->get_records('forum_discussions', [...], 'created ASC')` fails with a swallowed "Error reading from database". Sort by `timemodified` (full columns: `id,course,forum,name,firstpost,userid,groupid,assessed,timemodified,usermodified,timestart,timeend,pinned,timelocked`).
- **Site admins have no course role assignments** — a staff set built purely from level-50 non-student role assignments misses the admin's own posts (see reply-check workflow step 3).
- `mdl_forum_subscriptions` has only `id, userid, forum, preference` — per-user-per-forum, no per-discussion subscription column to copy.
- Copy `usermodified` (not just `userid`) on the discussion row — the listing's "last posted by" JOIN uses it.
- FAQ posts in these courses are authored by user 2 (Dr Chan); keep `userid=2` on copies so they stay in his authorship.
- When fixing wording in a post, update it in ALL courses that carry the copy — then `moosh -n cache-clear`.
