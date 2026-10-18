---
name: moodle-curl-security-for-ai
description: "Diagnose and fix Moodle cURL security blocking AI provider API calls on non-standard ports or internal IPs. Common error: 'Something Went Wrong' on AI summarize/generate."
---

# Moodle cURL Security for AI Providers

## Trigger

- AI summarize, generate text, or explain returns "Something Went Wrong"
- AI provider endpoint is accessible from curl but not from Moodle
- Internal Kubernetes services or non-standard ports (e.g., 8000) for AI APIs

## Root Cause

Moodle's `core\files\curl_security_helper` blocks all outbound HTTP requests to:
1. **Ports other than 80 and 443** by default
2. **Internal/private IP ranges** (10.x, 172.16-31.x, 192.168.x)
3. **Hosts that resolve to private IPs** (Kubernetes service names like `*.svc.cluster.local`)

The error is swallowed — the UI just shows "Something Went Wrong".

## Diagnosis

Enable debug mode temporarily and trigger an AI action via PHP:

```bash
# Enable debug
cd <webroot> && moosh -n sql-run "UPDATE mdl_config SET value = 'E_ALL | E_STRICT' WHERE name = 'debug'"
cd <webroot> && moosh -n sql-run "UPDATE mdl_config SET value = '1' WHERE name = 'debugdisplay'"

# Trigger a test summarize call
cd <webroot> && moosh -n php-eval "
global \$DB;
\$action = new core_ai\aiactions\summarise_text(
    contextid: 18,
    userid: 2,
    prompttext: 'Test message.',
);
\$manager = core\di::get(core_ai\manager::class);
\$response = \$manager->process_action(\$action);
echo 'Success: ' . var_export(\$response->get_success(), true) . PHP_EOL;
if (!\$response->get_success()) {
    echo 'Error: ' . \$response->get_errormessage() . PHP_EOL;
    echo 'Code: ' . \$response->get_errorcode() . PHP_EOL;
}
"
```

Look for: `++ Blocked The URL is blocked. [user 2] ++`

**Always revert debug mode afterward:**
```bash
cd <webroot> && moosh -n sql-run "UPDATE mdl_config SET value = '0' WHERE name = 'debug'"
cd <webroot> && moosh -n sql-run "UPDATE mdl_config SET value = '0' WHERE name = 'debugdisplay'"
```

## Fix: Allow the port

Add the port to Moodle's allowed ports list:

```bash
cd <webroot> && moosh -n sql-run "UPDATE mdl_config SET value = '443\n80\n8000' WHERE name = 'curlsecurityallowedport'"
cd <webroot> && moosh -n php-eval "purge_all_caches();"
```

Or use the UI: **Site admin → Security → HTTP Security → Allowed ports**.

## Fix: Allow internal hosts

If the host resolves to a private IP and port isn't the issue, add the hostname to an allow list. The cURL security helper checks `curlsecurityblockedhosts` (a blocklist). If no blocked hosts are configured, all hosts pass — but if blocked hosts _are_ configured, internal IPs fail.

**Check current config:**
```bash
cd <webroot> && moosh -n php-eval "
global \$CFG;
echo 'Blocked hosts: ' . var_export(\$CFG->curlsecurityblockedhosts ?? '', true) . PHP_EOL;
echo 'Allowed ports: ' . var_export(\$CFG->curlsecurityallowedport ?? '', true) . PHP_EOL;
"
```

## Key code reference

- Security check: `/lib/classes/files/curl_security_helper.php`
- Guzzle middleware: `/lib/classes/local/guzzle/check_request.php`
- Port check: `curlsecurityallowedport` config (newline-separated)
- Host blocklist: `curlsecurityblockedhosts` config (newline-separated)
