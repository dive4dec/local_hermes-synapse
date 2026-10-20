<?php
// mhs_probe.php — READ-ONLY environment probe for the mhs-setup meta-skill.
// Emits a single JSON object on stdout describing the live Moodle install:
//   version (big Moodle version number), wwwroot, host, datadir, dbhost/port,
//   SMTP settings, candidate courses, and the "helpers" group id.
// It NEVER writes to the DB, .env, or filesystem. Safe to re-run.
//
// Usage:  php mhs_probe.php [webroot]
//         webroot defaults to $MHS_WEBROOT, then /var/www/html/public.
//
// The version number is Moodle's big integer (e.g. 2026042001 == 5.2.1).
// mhs-setup gates on this: the portable skill set assumes Moodle 5.2+, so the
// floor is the 5.2-series version number (see MHS_MIN_VERSION in the skill).

$WEBROOT = isset($argv[1]) ? rtrim($argv[1], '/')
                            : (getenv('MHS_WEBROOT') ?: '/var/www/html/public');

$out = [
    'webroot'   => $WEBROOT,
    'error'     => null,
    'version'   => null,
    'release'   => null,
    'wwwroot'   => null,
    'host'      => null,
    'datadir'   => null,
    'dbhost'    => null,
    'dbport'    => null,
    'dbname'    => null,
    'smtphosts' => null,
    'smtpport'  => null,
    'noreply'   => null,
    'courses'   => [],
    'helpers'   => [],
];

if (!is_file($WEBROOT . '/config.php')) {
    $out['error'] = "config.php not found at {$WEBROOT}/config.php — set MHS_WEBROOT to the Moodle webroot and re-run.";
    echo json_encode($out, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
    exit(0);
}

try {
    if (!defined('CLI_SCRIPT')) define('CLI_SCRIPT', true);
    if (!defined('MOODLE_INTERNAL')) define('MOODLE_INTERNAL', true);
    require($WEBROOT . '/config.php');
    global $CFG;

    $out['version'] = isset($CFG->version) ? (int)$CFG->version : null;
    $out['release'] = isset($CFG->release) ? (string)$CFG->release : null;
    $out['wwwroot'] = isset($CFG->wwwroot) ? $CFG->wwwroot : null;
    $out['datadir'] = isset($CFG->directory) ? $CFG->directory
                    : (isset($CFG->dataroot) ? $CFG->dataroot : null);
    $out['dbhost']  = isset($CFG->dbhost) ? $CFG->dbhost : null;
    $out['dbport']  = isset($CFG->dbport) ? $CFG->dbport : null;
    $out['dbname']  = isset($CFG->dbname) ? $CFG->dbname : null;
    if (!empty($CFG->wwwroot)) {
        $out['host'] = parse_url($CFG->wwwroot, PHP_URL_HOST);
    }
    $out['smtphosts'] = isset($CFG->smtphosts) ? $CFG->smtphosts : null;
    $out['smtpport']  = isset($CFG->smtpport) ? $CFG->smtpport : null;
    $out['noreply']   = isset($CFG->noreplyaddress) ? $CFG->noreplyaddress : null;

    // DB-backed candidates (best effort; a missing DB never kills the probe).
    try {
        global $DB;
        if (!isset($DB)) {
            require_once($WEBROOT . '/lib/setup.php');
            global $DB;
        }
        $rows = $DB->get_records('course', ['id' => ['>' => 0]], 'id ASC', 'id,fullname,shortname', 0, 100);
        foreach ($rows as $r) {
            $out['courses'][] = ['id' => (int)$r->id, 'fullname' => $r->fullname, 'shortname' => $r->shortname];
        }
        $h = $DB->get_records('groups', ['name' => 'helpers'], 'id ASC', 'id,name,courseid', 0, 50);
        foreach ($h as $r) {
            $out['helpers'][] = ['id' => (int)$r->id, 'name' => $r->name, 'courseid' => (int)$r->courseid];
        }
    } catch (Throwable $e) {
        $out['db_error'] = $e->getMessage();
    }
} catch (Throwable $e) {
    $out['error'] = 'Moodle bootstrap failed: ' . $e->getMessage();
}

echo json_encode($out, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
