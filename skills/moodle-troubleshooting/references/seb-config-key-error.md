# SEB "Invalid SEB config key" Error

## Session example (2026-08-13)

Adam LTITEST (user id=496) tried to access "Quiz for testing SEB" (quiz id=55) in <coursecode> via Safe Exam Browser. Access was repeatedly denied.

### Log entries

```
eventname: \quizaccess_seb\event\access_prevented
objecttable: quiz
objectid: 55
other: {"reason":"Invalid SEB config key","savedconfigkey":"1af776b9a093371dcf03ae433ee8be8b213fd4232b714698d97fafe4b7f094cc","receivedconfigkey":"734db1c2481ed22fa56482ef15b51da20152eeb6552f3c24fdb93115da51...","receivedbrowserexamkey":null}
```

In some attempts, `receivedconfigkey` was `null` — meaning SEB sent no config key at all.

### Root cause

The student's Safe Exam Browser client had a stale `.seb` configuration file whose stored hash didn't match Moodle's current `savedconfigkey`. This happens when:
1. The quiz SEB settings were regenerated on Moodle after the student downloaded the config
2. The student copied their SEB config from a different quiz or course
3. SEB cache wasn't refreshed

### Fix

Student must click the SEB download link on the quiz page to get the latest `.seb` config, then launch SEB with that fresh config.

### Diagnosis pattern

```php
$logs = $DB->get_records('logstore_standard_log', ['userid' => $uid, 'courseid' => $cid], 'id DESC', '*', 0, 5);
foreach ($logs as $log) {
    if ($log->action === 'prevented') {
        $data = json_decode($log->other, true);
        echo "Reason: {$data['reason']}\n";
        echo "Expected key: {$data['savedconfigkey']}\n";
        echo "Got key: " . ($data['receivedconfigkey'] ?? 'null') . "\n";
    }
}
```
