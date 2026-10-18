---
name: moodle-cequiz-schedule-propagation
description: "Fix CE-Quiz and E-Quiz timing and group overrides for cs1302a_26a based on weekly lab schedule and semester schedule. Handles catch-up weeks, helpers group, and E-Quiz one-week-earlier windows."
---

# CE-Quiz and E-Quiz Schedule Propagation

Fix CE-Quiz and E-Quiz timing, group overrides, and lab session groups after restoring from backup files with stale data.

## Triggers

- CE-Quiz/E-Quiz timing is wrong or from old semester
- Group overrides are stale
- Lab sections missing (e.g., T01, T02, TA1)
- "Fix CE-Quiz timing", "propagate quiz changes"

## Core mapping

- **CE-Quiz N = Lab N = Week (N+2)** — CE-Quiz 1 is Lab1 in Week 3, CE-Quiz 2 is Lab2 in Week 4, etc.
- **E-Quiz N runs one week before CE-Quiz N** — same week window but shifted 7 days earlier.
- Lab0 is a demo quiz (quiz 56) with no group overrides.
- Week 8 has no regular labs — only catch-up for CE3/CE4/CE5 Thursday sessions.
- Week 9 is Lab6/CE6.

## Group ID reference (course cs1302a_26a)

| Group | ID |
|---|---|
| T01, T02, TA1 | 93, 94, 95 |
| LA1–LA4 | 64, 56, 63, 70 |
| LB1–LB3 | 62, 69, 72 |
| LC1–LC3 | 68, 58, 77 |
| helpers | 89 |

## Weekly lab schedule template

Days relative to Monday: 0=Mon, 1=Tue, 2=Wed, 3=Thu

| Day | Time | Groups |
|---|---|---|
| Mon (0) | 10:00 | T02 |
| Mon (0) | 14:00 | LA4 |
| Mon (0) | 15:00 | T01, TA1, LA3 |
| Mon (0) | 16:00 | LA2 |
| Tue (1) | 12:00 | T02 |
| Wed (2) | 12:00 | LA1, LB2, LC2 |
| Thu (3) | 11:00 | LB1, LC1 |
| Thu (3) | 12:00 | LB3, LC3 |

## Steps

### 1. Create missing groups

Use Moodle API (`$DB->insert_record('groups', ...)`) for any groups not in the database (T01, T02, TA1).

### 2. For each CE-Quiz

a. **Update global quiz times** — set `timeopen` to Monday 00:00 and `timeclose` to Sunday 23:59 of the corresponding week.

b. **Delete all existing overrides** — `delete_records('quiz_overrides', ['quiz' => $quizId])`.

c. **Create group overrides** — one per group per time slot. Each override:
   - `timeopen`: slot start
   - `timeclose`: slot start + 50 minutes
   - `timelimit`: **2700** (must match quiz default, not 0)
   - `attempts`: **1** (must match quiz default, not 0)
   
   **IMPORTANT:** Do NOT set `timelimit=0` or `attempts=0` expecting Moodle to inherit — it doesn't. Set them to the same values as the quiz defaults.

d. **Catch-up weeks** — CE3 (week 5) misses Thu; CE4 (week 6) misses Thu; CE5 (week 7) misses Thu. Their Thursday sessions are scheduled in the following weeks:
   - CE3 catch-up: Thu Oct 1 (Week 6)
   - CE4 catch-up: Thu Oct 14 (Week 7)
   - CE5 catch-up: Thu Oct 22 (Week 8)

e. **Helpers override** — group 89, `timeopen` = one week before quiz, `timeclose` = quiz Sunday, `timelimit=2700`, `attempts=0` (unlimited).

### 3. For each E-Quiz

Set `timeopen` and `timeclose` to the week before the corresponding CE-Quiz. E-Quizzes have no group overrides.

### 4. Purge caches

```bash
php script.php 2>&1
cd /var/www/html/public && moosh -n cache-clear
```

Always run `moosh -n cache-clear` AFTER the PHP script's own cache purge.

## Key quiz IDs

| Quiz | Type | ID |
|---|---|---|
| Quiz for testing SEB | test | 55 |
| Demo CE-Quiz | demo | 56 |
| CE-Quiz 1–9 | CE | 58, 60, 62, 64, 66, 68, 70, 72, 74 |
| E-Quiz 1–9 | E | 57, 59, 61, 63, 65, 67, 69, 71, 73 |

## Pitfalls
## Pitfalls
- **`timelimit=0` and `attempts=0` do NOT inherit from quiz defaults** — Moodle uses those values literally for overrides. Always set them to match the quiz (2700 and 1).
- **`userid IS NOT NULL` is NOT a "user-level override" test** — group-level lab overrides are stored with `userid=0` (not NULL). Use `o.userid > 0` for real per-user overrides and `o.groupid=91` for the teacher group. (2026-10-05: the 45 lab-group rows on CE-Quizzes all have userid=0; an `IS NOT NULL` check falsely reported them.)
- **Stale teacher-group (g91) overrides break the cover page for teachers only** — the cover page resolves the most specific override, so a leftover g91 row (e.g. 2025 dates from a restore) makes E-Quiz/CE-Quiz cover pages show the wrong date for u494/u495 while global settings and all students show the correct window. Audit pattern: `quiz_overrides` joined to course-3 quizzes with `groupid=91 OR userid>0`. Fix = backup + delete the stale rows + `purge_caches()` + `moosh -n cache-clear` (2026-10-05, overrides 409/431/453/475/497/519 on E-Quiz 4-9).
- **Always run `moosh -n cache-clear` after PHP script** — the script's `cache_helper::purge_by_event()` alone is insufficient.
- **Catch-up weeks** — Week 5 has no Thu, Week 6 has no Thu, Week 7 has no Thu. CE3/4/5 Thursday sessions shift to the following week's Thursday.
- **LB2/LC2 are on Wednesday, not Thursday** — they are with XU Weitao's Wednesday 12:00 session.
- **Use Moodle PHP API, not raw SQL** — always bootstrap with `define('CLI_SCRIPT', TRUE)` and `require_once('/var/www/html/config.php')`.