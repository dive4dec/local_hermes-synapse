---
name: moodle-smtp-email
description: "Find Moodle SMTP configuration and send test emails via PHPMailer within the Moodle framework."
---

# Moodle SMTP Configuration & Email Testing

Find SMTP settings and send test emails from within the Moodle pod.

## Triggers

- User asks to send a test email
- User asks to check SMTP/mail configuration
- User needs to verify email delivery from Moodle
- "can you email me", "test SMTP", "check email config"

## Find SMTP config

Boot the full Moodle framework and read `$CFG` directly:

```php
<?php
define('CLI_SCRIPT', TRUE);
$_SERVER['REQUEST_URI'] = '/';
$_SERVER['SCRIPT_NAME'] = '/admin/cli/check-smtp.php';
require_once('/var/www/html/config.php');

$cfgNames = ['smtphosts', 'smtpport', 'smtpsecure', 'smtpuser', 'smtppass', 'smtpauthtype', 'noreplyaddress', 'noreplyname', 'mailfromaddress', 'fromname'];
foreach ($cfgNames as $name) {
    $val = isset($CFG->$name) ? $CFG->$name : '(not set)';
    if ($name === 'smtppass') $val = '***';
    echo "  $name: $val" . PHP_EOL;
}
?>
```

Key `$CFG` properties:
- `$CFG->smtphosts` — host, may include port (e.g., `smtp.example.com:587`)
- `$CFG->smtpport` — explicit port if separate from host
- `$CFG->smtpsecure` — TLS/SSL mode
- `$CFG->smtpuser` / `$CFG->smtppass` — SMTP credentials
- `$CFG->smtpauthtype` — auth mechanism (e.g., `LOGIN`)
- `$CFG->noreplyaddress` — default from address
- `$CFG->fromname` — default from name

## Send email via PHPMailer

PHPMailer is available in the Moodle pod. Write a script that boots Moodle framework, reads `$CFG` SMTP settings, and sends via PHPMailer:

```php
<?php
define('CLI_SCRIPT', TRUE);
$_SERVER['REQUEST_URI'] = '/';
$_SERVER['SCRIPT_NAME'] = '/admin/cli/send-email.php';
require_once('/var/www/html/config.php');

use PHPMailer\PHPMailer\PHPMailer;
use PHPMailer\PHPMailer\Exception;

// Parse host:port from smtphosts
$hosts = explode(',', $CFG->smtphosts ?? '');
$host = trim($hosts[0]);
$port = 587;
if (preg_match('/^(.*):(\d+)$/', $host, $m)) {
    $host = $m[1];
    $port = (int)$m[2];
}
if (isset($CFG->smtpport) && $CFG->smtpport) {
    $port = (int)$CFG->smtpport;
}

$mailer = new PHPMailer(true);
$mailer->isSMTP();
$mailer->Host = $host;
$mailer->Port = $port;
$mailer->SMTPSecure = $CFG->smtpsecure ?? '';
$mailer->SMTPAuth = !empty($CFG->smtpuser);
if ($mailer->SMTPAuth) {
    $mailer->Username = $CFG->smtpuser;
    $mailer->Password = $CFG->smtppass ?? '';
}
$mailer->SMTPDebug = 2;

$mailer->setFrom($CFG->noreplyaddress ?? 'noreply@example.com', $CFG->fromname ?? 'Moodle');
$mailer->addAddress('recipient@example.com');
$mailer->Subject = 'Test Email';
$mailer->Body = "Test email from Moodle.";

if ($mailer->send()) {
    echo "SUCCESS\n";
} else {
    echo "FAILED\n";
}
?>
```

Run with: `php /tmp/send-email.php 2>&1`

## Pitfalls

- **`moosh php-eval` not available:** moosh 1.27 does not have `php-eval`. Write a PHP file and run it directly.
- **Must boot Moodle framework:** Include `config.php` with `CLI_SCRIPT` defined to access `$CFG` settings. Don't query the DB directly — DB password is tricky and connection may be denied from the pod's IP.
- **`email_to_user_addr()` doesn't exist in Moodle 5.2:** The old email function was removed. Use PHPMailer directly.
- **`core\email\manager` doesn't exist:** Moodle 5.2 uses a different email system. PHPMailer is the reliable approach.
- **Empty noreplyaddress:** If the user clears the noreply address in the admin UI, `$CFG->noreplyaddress` becomes an empty string (not a default). You must fall back to something like `noreply@dive.cs.cityu.edu.hk` derived from `wwwroot`. PHPMailer will reject an empty from address.
- **SMTP password:** `$CFG->smtppass` is the plaintext password (not base64) when accessed through the Moodle framework. Only `config.php` has base64-encoded DB passwords.
- **`SMTPDebug = 2`** gives verbose SMTP transcript — essential for diagnosing failures. Set to `0` for production.
- **Scripts go in `/tmp/`:** Always write temporary PHP scripts to `/tmp/` to avoid polluting the Moodle filesystem.
