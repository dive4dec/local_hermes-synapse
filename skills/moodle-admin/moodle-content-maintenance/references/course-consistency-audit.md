# Audit a Moodle course for internally inconsistent content

A read-only "sanity pass" over one course (e.g. "check if there's any inconsistent
content in cs1302a_26a"). Cross-check things that *should* agree but drift apart after
clones, copy-pastes, and semester rollovers. Read-only: gather evidence, then present a
prioritized change list and wait for the user's per-item go/no-go (the user's standing
rule: list exact changes, confirm, THEN apply).

## Checklist (what actually paid off on course 3, 2026-08-27)

1. **Announcement post vs activity reality.** Pull the "Announcements" (`type='news'`)
   forum's pinned/first post and compare every claim to the live activity:
   - Dates/times/durations of exams, midterms, quizzes. (Found: post said 18:30–19:30 but
     the Midterm quiz was locked 18:30→19:45 — a real discrepancy, even if the user later
     says the buffer is intentional.)
   - "from the <Section> section" references — resolve each named section/label/page and
     confirm it exists and is visible. (Found: "Syllabus section" referenced but no such
     section — user had since changed it to the existing "Overview".)
2. **Cross-course `view.php?id=` links.** A relative link like
   `../mod/resource/view.php?id=N` resolves to **whichever course owns CM N**. If CM N's
   `course` field is a *different* course, the link breaks/403s for this course's
   students (they aren't enrolled there). Scan every `label.intro`/`page`/`forum` for
   `view\.php\?id=(\d+)`, then `SELECT course FROM mdl_course_modules WHERE id=:N`.
   (Found: all 9 "Reading" labels linked to 25b's textbook CM 97; 26a's own textbook was
   CM 196 — same PDF by content hash, so re-pointing preserved `#page=` anchors.)
   Verify two resources are the same file by comparing `mdl_files.contenthash`.
3. **Copy-pasted forum intros.** `SELECT id,name,course,intro FROM mdl_forum WHERE
   course=:cid` and eyeball for a name/intro mismatch. (Found: "Project FAQ" intro said
   "Clarifications for CE-Quiz…" — a copy-paste of the CE-Quiz FAQ.)
4. **Gradebook weight sums + total display scale.** Sum `aggregationcoef2` over the
   counted (non-hidden, non-zero) items and compare to the plan; check the course-item
   `grademax` and `display`. See the `moodle-gradebook` skill — a Natural/SUM course
   shows a raw point total (e.g. /1025), not a percentage.
5. **Stale groupings.** For each `grouping`, join `groupings_groups g → groups`; groups
   whose name is NULL are deleted leftovers from a prior section scheme (e.g. LA/LB/LC
   → T01/T02/TA1). Harmless to render but messy. Confirm no `quiz_overrides`/role
   assignments reference the stale ids before removing them.
6. **Leftover "(copy)" labels / junk.** Grep `label.name` for ` (copy)` and inspect
   `intro` for mangled markdown. Check the module context has 0 files before deleting.
7. **Visible-but-empty URL resources.** `url` resources with `visible=1` and empty `url`
   show to students but go nowhere. (May be intentional — ask, don't assume.)
8. **Group overrides, slot by slot.** For each CE-Quiz/E-Quiz, list
   `quiz_overrides` joined to `groups` with `timeopen/timeclose`. Cross-check each group
   is in the right lab slot (see `moodle-cequiz-schedule-propagation`). Flag any group in
   a slot its tutor doesn't own.
9. **Orphan groups.** Groups in a grouping with 0 members and no overrides (e.g. a
   late-added T03) — flag as "new section not yet wired up" rather than deleting.

## Method notes

- The `moodle_db` MCP `query` tool is ideal for the read-heavy steps; use the PHP
  bootstrap (`moodle-db-access`) when the keyword filter blocks a column or you need to
  write.
- `mdl_forum_discussions.name` is the discussion title; `mdl_forum_posts.discussion`
  links posts to a discussion (no `discussionid`).
- `mdl_groups` visibility column is `visibility` (not `visible`); `mdl_quiz` has
  `timelimit`+`attempts` (no `timegradelimit`); `groupmode` is on `mdl_course_modules`.
- Don't over-claim: present findings as *discrepancies to review*, let the user rule on
  intent (several "discrepancies" here turned out to be deliberate — the 15-min buffer,
  the empty clinics URL).
