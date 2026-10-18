---
name: moodle-lock-profile-editing
description: "Lock Moodle users from editing their own profile (especially email). Covers why updateemailaddress config no longer works, auth plugin field locks, and the role capability approach."
---

# Moodle Lock Profile Editing

## Trigger

- Prevent students from changing their email address
- Lock profile fields (name, email, etc.) to avoid breaking external systems
- Secure user identity for LTI integration or central authentication

## Problem

Moodle 5.2 **removed** the `updateemailaddress` core config setting. The only way to prevent email changes is now through role capabilities or auth plugin field locks.

## Option 1: Auth plugin field locks (recommended if applicable)

Each auth plugin has `field_lock_email` setting:

- **UI**: Site admin → Plugins → Authentication → [plugin] → Locked fields
- **DB**: `mdl_config_plugins` where `plugin = 'auth_email'` and `name = 'field_lock_email'`
- Set to `locked`

**Limitation:** Only works for users authenticated via that plugin. If your users are LTI-authenticated, `auth_email` field locks don't apply to them.

Check which auth plugins your site uses:
```bash
cd /var/www/html/public && moosh -n php-eval "
global \$DB, \$CFG;
echo 'Site auth: ' . \$CFG->auth . PHP_EOL;
\$users = \$DB->get_records_sql('SELECT auth, COUNT(*) as cnt FROM mdl_user GROUP BY auth');
foreach (\$users as \$u) { echo \$u->auth . ': ' . \$u->cnt . ' users' . PHP_EOL; }
"
```

## Option 2: Role capability Prohibit (covers all users)

Set `moodle/user:editownprofile` to **Prohibit** on the **Authenticated user** role.

**Why the basic role edit form doesn't show Prohibit:**

The role editing page has a **Basic** and **Advanced** view. The basic view only shows an "Allow" checkbox. You must click **"Show advanced"** to see all four permission states (Inherit/Allow/Prevent/Prohibit).

Code: `admin/roles/classes/define_role_table_basic.php` — the basic table class only renders a checkbox for Allow.

**To set via DB:**
```bash
cd /var/www/html/public && moosh -n php-eval "
global \$DB;
\$DB->execute('UPDATE mdl_role_capabilities SET permission = 3 WHERE roleid = 7 AND capability = ? AND contextid = 1', ['moodle/user:editownprofile']);
purge_all_caches();
echo 'Done';
"
```

- `roleid = 7` = Authenticated user
- `permission = 3` = Prohibit
- `contextid = 1` = system-wide

**Consequences:**
- **No one** can edit their own profile (email, name, password, profile picture, etc.)
- Managers still work (they have explicit Allow)
- Users who need to change their password must use the **forgot password** flow (`/login/forgot_password.php`)
- Prohibit is absolute — only a more specific context or higher-priority role can override it

## Permission states reference

| Value | Constant | Meaning |
|---|---|---|
| 0 | `CAP_INHERIT` | Inherit from higher context or parent role |
| 1 | `CAP_ALLOW` | Grant permission |
| 2 | `CAP_PREVENT` | Deny unless overridden by Allow |
| 3 | `CAP_PROHIBIT` | Absolute deny, cannot be overridden |

## How Moodle resolves capabilities

1. A user's roles are evaluated across all applicable contexts (system, course, activity)
2. Each role may have explicit (Allow/Prevent/Prohibit) or inherited permission
3. **Prohibit always wins** — if any role in any context has Prohibit, the capability is denied
4. Allow beats Prevent, but loses to Prohibit
5. If nothing is set (Inherit), the capability definition's default is used

## Example: Why students can edit profiles even when Student role doesn't have editownprofile

```
User "Temirlan ADAMOV":
  System: Authenticated user → moodle/user:editownprofile = Allow
  Course: Student → moodle/user:editownprofile = Not set (Inherit)
Result: Allow (inherited from Authenticated user)
```

Even though the Student role shows "unchecked" for the capability, the user still has it from Authenticated user. Setting Authenticated user to Prohibit fixes this.
