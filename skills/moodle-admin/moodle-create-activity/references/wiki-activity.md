# Wiki (mod/wiki) — Group Modes, Comments, and Deadline Locking

Verified in this environment (Moodle 5.2.x, `CFG->version=2026042001`) by reading `/var/www/html/public/mod/wiki/`. Re-verify line numbers before quoting, but the semantics are structural and stable.

## Group-mode access semantics

From `wiki_user_can_view()` / `wiki_user_can_edit()` in `mod/wiki/locallib.php`:

| CM groupmode | View | Edit |
|---|---|---|
| `NOGROUPS` (0) | `mod/wiki:viewpage` | `mod/wiki:editpage` |
| `SEPARATEGROUPS` (1) | Own-group members only; non-members need `managewiki` (or `moodle/site:accessallgroups`) + `viewpage` | Own-group members with `editpage`; non-members need `managewiki` + `accessallgroups` + `editpage` |
| `VISIBLEGROUPS` (2) | **Everybody** with `mod/wiki:viewpage` (students have it by default) | Own-group members with `editpage`; non-members need `managewiki` + `editpage` (effectively teachers only) |

Key consequences:
- **Cross-group viewing is impossible in SEPARATEGROUPS.** If students must browse all groups' pages (peer review), the activity must be VISIBLEGROUPS.
- **No capability overrides are needed** to restrict editing to group members in VISIBLEGROUPS — the group-membership check is built into the code.
- One subwiki per group in `wiki_subwikis` (`wikiid, groupid, userid=0` for collaborative mode). Subwikis and first pages are **created lazily** on first view (`view.php` redirects to `create.php` if missing) — do NOT pre-create 100 subwikis/pages up front.
- `wiki` table: `wikimode='collaborative'` = one wiki per group; `'individual'` = one wiki per user.

## There is NO native "editable until" date

- The `wiki` table has `editbegin`/`editend` columns, but they are **never enforced anywhere in module code** (only touched by backup/restore date-shifting and the WS). The wiki edit form has no date fields. Setting them does nothing.
- **Deadline-lock pattern**: at the deadline, add a `role_capabilities` row for the student role at the **module context**: `capability='mod/wiki:editpage'`, `permission=CAP_PREVENT` (1 = allow, -1 = prevent, 0 = inherit). That freezes all student editing site-consistently.
- `mod/wiki:overridelock` is for concurrent-edit conflicts (`wiki_locks` table, per page/section) — **not** a deadline mechanism. `wiki_pages.readonly` is also not enforced in the edit path.

## Two-phase peer-review pattern (proven plan shape)

Used for cs1302a_26a project wiki (100 groups, grouping id 25):

1. **Phase A** (creation → review opens): CM `groupmode=1` (SEPARATEGROUPS) + `groupingid=<project grouping>`. Each group sees/edits only its own page.
2. **Phase B** (review opens): flip the same `course_modules` row's `groupmode` from 1 → 2 (VISIBLEGROUPS). One-field update; subwikis/pages/comments unaffected. All students can now view all group pages and comment.
3. **Phase C** (deadline): insert the PREVENT capability row (optionally also `mod/wiki:editcomment`) to freeze.

Note: these phase changes are one-off flips — ask the user whether they want to be pinged vs a system crontab on the pod; a Hermes cronjob across weeks is not reliable to rely on.

## Comments

- Gated by site setting `config.usecomments` (verified `=1` on this site) and `mod/wiki:viewcomment`.
- `comments.php` first checks `wiki_user_can_view($subwiki, $wiki)` — so in VISIBLEGROUPS any student can comment on any group's page; in SEPARATEGROUPS only own-group members can even see the comments tab.
- Student role defaults already grant `mod/wiki:viewcomment=1` and `mod/wiki:editcomment=1`.

## Page format

- `wiki.defaultformat` must be one of `html`, `creole`, `nwiki` (`wiki_get_formats()`). This is independent of the site's default rich-text editor. `forceformat=1` locks students to it.
- `firstpagetitle` is the per-group landing page title; later pages are created via the "New page" link inside each subwiki.

## Navigation limitation (important for multi-group wikis)

- The wiki UI does **not** render a group-switching dropdown (`pagelib.php` has no group selector). In VISIBLEGROUPS students cannot click their way from group00's page to group01's page.
- Solution: add a "directory" label/resource with direct links to each group's first page. URL shape that works: `/mod/wiki/view.php?id=<cmid>&wid=<wikiid>&group=<groupid>&title=<firstpagetitle>` (the `group` param sets the active group for the user; verified against `view.php` case 2 and `grouplib.php:groups_get_activity_group`).
- With 100 groups, generate the link list programmatically from `groupings_groups` for the grouping.

## Creation field reference (wiki table)

```
course, name, intro (MOODLE/WYSIWYG text), introformat (1 = HTML),
timecreated, timemodified, firstpagetitle,
wikimode ('collaborative'), defaultformat ('html'), forceformat (1),
editbegin (0), editend (0)
```

Create via the standard direct-DB-insert flow in SKILL.md (insert `wiki` instance → insert `course_modules` with `groupmode`/`groupingid` set → link `instance` → append to section sequence → `context_module::instance($cmid, true)` → purge `core_coursemodinfo` file cache + `moosh -n cache-clear`).
