---
name: moodle-seb-quiz-access
description: "Diagnose and fix Safe Exam Browser (SEB) access issues for Moodle quizzes. Covers config key mismatches, template assignment, and SEB modes."
---

# Moodle SEB Quiz Access

Diagnose and fix Safe Exam Browser access failures for Moodle quizzes.

## SEB Modes (`requiresafeexambrowser`)

| Value | Constant | Description |
|---|---|---|
| `0` | `USE_SEB_NO` | SEB not required |
| `1` | `USE_SEB_CONFIG_MANUALLY` | Individual SEB options set per quiz |
| `2` | `USE_SEB_TEMPLATE` | Uses a reusable SEB template |
| `3` | `USE_SEB_UPLOAD_CONFIG` | Expects an uploaded `.seb` config file |
| `4` | `USE_SEB_CLIENT_CONFIG` | Client-side config |

## Key Tables

- `quizaccess_seb_quizsettings` — per-quiz SEB settings (`quizid`, `cmid`, `templateid`, `requiresafeexambrowser`)
- `quizaccess_seb_template` — SEB templates (`id`, `name`)

## SEB Plugin Location

`<webroot>/mod/quiz/accessrule/seb/`

## Common Error: "Invalid SEB config key"

When a student's SEB config doesn't match Moodle's stored config key, logs show:

```json
{"reason":"Invalid SEB config key","savedconfigkey":"...","receivedconfigkey":null,"receivedbrowserexamkey":null}
```

**Fix**: Assign the correct SEB template to the quiz.

## Assign Template to All Quizzes in a Course

```php
$settings = $DB->get_records('quizaccess_seb_quizsettings');
foreach ($settings as $s) {
    $quiz = $DB->get_record('quiz', ['id' => $s->quizid]);
    if ($quiz && $quiz->course == $courseid) {
        $DB->set_field('quizaccess_seb_quizsettings', 'templateid', $templateid, ['id' => $s->id]);
        $DB->set_field('quizaccess_seb_quizsettings', 'requiresafeexambrowser', 2, ['id' => $s->id]);
    }
}
```

Always purge caches after: `php admin/cli/purge_caches.php`

## SEB Config Key Flow

1. Quiz defines SEB settings (manually, template, or uploaded file)
2. Moodle generates a config key hash from the settings
3. Student downloads/receives the SEB config (via `seb://` launch link or HTTP download)
4. SEB sends the config key back in HTTP headers when accessing the quiz
5. Moodle validates the received key matches the stored key

If the student opens SEB with a stale config, the keys won't match and access is denied.

## Checking Logs

```php
$logs = $DB->get_records('logstore_standard_log',
    ['userid' => $uid, 'courseid' => $cid], 'id DESC', '*', 0, 30);
// Check $log->other for SEB JSON details
// Check $log->objectid for quiz id
```

## Pitfalls

- Mode 3 (upload config) with no uploaded file will always fail — SEB has nothing to validate against
- Multiple users with the same name exist as separate accounts (check user id, not just name)
- `mdl_quiz` has no SEB columns — settings are in `quizaccess_seb_quizsettings`
- The `showseblinks` global config controls which buttons appear: `seb` = Launch SEB button, `http` = Download config button
- **Do not deduce a campus/lab IP range from a single observed IP.** A single address (e.g. `<lab-ip>`) proves nothing about the subnet; on this site the logstore only ever showed that ONE `175.159.*` address, so the valid lab range must come from the lab's network docs, not from logs. `175.159.*` is not within `MOODLE_AUDIT_CAMPUS_IPS` (10/8, 144.214/16, 172.16/12), so audits flag it non-campus until the user adds the lab's real CIDR(s) to `.env`.
