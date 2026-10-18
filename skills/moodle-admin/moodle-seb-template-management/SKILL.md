---
name: moodle-seb-template-management
description: "Bulk-standardize SEB (Safe Exam Browser) template config across quizzes on <moodle-host> (Moodle 5.x): what template mode actually generates, the allowuserquitseb NULL trap, the required 3-cache purge, and post-change config verification. Use when switching a course's quizzes to a different SEB template (e.g. enabling URL filtering 'like quiz X'), when students report missing/mismatched SEB config after a template change, or when checking what SEB config a quiz will serve."
---

# SEB Template Management (bulk standardization, Moodle 5.x)

Complements the manually-authored `moodle-seb-quiz-access` skill (diagnosis). This one covers
**changing** the SEB config a course's quizzes serve, done right.

## Triggers

- "Use the <X> SEB template / URL-filtering for all SEB quizzes in course Y, just like quiz Z"
- Students get "Invalid SEB config key" after a template was changed (stale cache)
- "What SEB config does quiz N actually serve?"

## How template mode builds the config (verified from source 2026-09-14)

`mod/quiz/accessrule/seb/classes/seb_quiz_settings.php` → `process_seb_template()`:

1. Start from the template XML: `mdl_quizaccess_seb_template.content` (parse as plist).
2. Layer per-quiz overrides — **only these**:
   - `allowuserquitseb` → `allowQuit` — computed as `allowuserquitseb == 1`, so **NULL = quit disabled**
   - `quitpassword` (if set), `quitURL` (if set in template or config)
3. Enforce: `startURL` = the quiz's `mod/quiz/view.php?id=<cmid>` URL, `sendBrowserExamKey = true`,
   `browserWindowWebView = 3`.
4. The whole plist is hashed into the **config key** (`config_key::generate()`).

**URL filtering is 100% template-driven.** The `activateurlfiltering` column on
`mdl_quizaccess_seb_quizsettings` is NOT read in template mode — to give quizzes URL
filtering, point them at a template whose XML contains `URLFilterEnable`.

Consequences:
- The generated config differs per quiz only by `startURL` (+ quit password/URL) — otherwise
  all quizzes on the same template serve an identical ruleset.
- Nothing else on the quiz row (time limits, attempts, …) affects the SEB config.

## The `allowuserquitseb` NULL trap

When standardizing a template across a course, first list which quizzes have
`allowuserquitseb` set to 1 vs NULL. A plain `templateid` switch keeps NULLs NULL →
those quizzes silently lose the SEB-quit button, even though the reference quiz had it.
**Always present both options to the user** ("template only" vs "template + match the
reference quiz's quit setting") and get the pick before writing.

## Bulk standardization recipe (verified 2026-09-14, course 3)

```php
<?php
define('CLI_SCRIPT', TRUE);
define('MOODLE_INTERNAL', true);
require('/var/www/html/public/config.php');
require_once('/var/www/html/public/lib/setup.php');
global $DB;

$quizids = [...];        // from: requiresafeexambrowser = 2 rows for the course
$now = time();
$modifier = <admin uid>;
foreach ($quizids as $qid) {
    $s = $DB->get_record('quizaccess_seb_quizsettings', ['quizid' => $qid]);
    if (!$s) continue;
    $s->templateid = <target template id>;
    $s->allowuserquitseb = 1;   // only if user chose "exactly like the reference quiz"
    $s->timemodified = $now;
    $s->usermodified = $modifier;
    $DB->update_record('quizaccess_seb_quizsettings', $s);
}

// 1) SEB state is application-cached — purge ALL THREE components or the old
//    config/configkey keeps being served (students stay locked out / keep old config):
foreach (['config', 'configkey', 'quizsettings'] as $c) {
    \cache::make('quizaccess_seb', $c)->purge();
}

// 2) Verify by regenerating from the DB (post-purge):
foreach ($quizids as $qid) {
    $cfg = \quizaccess_seb\seb_quiz_settings::get_config_by_quiz_id($qid); // plist XML
    // assert: '<key>URLFilterEnable</key><true/>' (if URL-filter template),
    // count of '<key>expression</key>' rules, '<key>startURL</key>', '<key>allowQuit</key>'
}
```

Also run `cd /var/www/html/public && moosh -n cache-clear` per site standard.
**No daemon/server restart needed** — config + key regenerate lazily per request;
students pick up the new config key on their next SEB launch.

## Pitfalls

- **Forgotten cache purge** = the classic "I changed the template but nothing changed" —
  the three `quizaccess_seb` cache components (`config`, `configkey`, `quizsettings`)
  are the ONLY reason a changed quiz keeps serving its old config key.
- **NULL `allowuserquitseb`** ≠ 1 — see the trap above; never assume NULL means "default on".
- **Wrong template id = silent wrong ruleset.** Templates have no enforced relationship to
  the quizzes using them; verify the template's `content` (it's raw plist XML in the DB)
  before standardizing, and name the reference quiz explicitly ("just like CE-Quiz 1" →
  read CE-Quiz 1's row: `templateid`, `allowuserquitseb`, `requiresafeexambrowser`).
- Scope the update to rows with `requiresafeexambrowser = 2` (template mode). Quizzes on
  manual/upload/client modes (1/3/4) or SEB-off (0) must not be switched by a blanket loop;
  list and exclude them in the change plan.
- Per-student config drill-down after a change: if someone still gets
  "Invalid SEB config key", the stored key now matches the new template — the mismatch is
  on the *student's* SEB side (they need to re-download the config / relaunch), not Moodle's.
- Course-3 specifics (template ids, the 21 quiz ids switched on 2026-09-14):
  `references/course-3-seb-templates.md`.
