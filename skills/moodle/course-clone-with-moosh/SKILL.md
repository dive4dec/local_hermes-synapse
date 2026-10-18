---
name: course-clone-with-moosh
description: "Clones a Moodle course to a new course without enrolled users using moosh course-backup --template and course-restore."
---

# Course Clone with Moosh (No Users)

## When to use this skill

Trigger when the user asks to clone, copy, or duplicate a Moodle course without enrolled students.

## Workflow

### Step 1: Find the source course ID

```bash
moosh -p <webroot> -n sql-run "SELECT id, shortname, fullname FROM mdl_course WHERE shortname = 'SOURCE_SHORTNAME'"
```

### Step 2: Template backup (excludes users, grades, user content)

```bash
moosh -p <webroot> -n course-backup SOURCE_ID --template -f /tmp/COURSE_TEMPLATE.mbz
```

The `--template` flag excludes:
- Course enrolments/users
- Grades
- User-generated content
- System-level question prototypes

### Step 3: Create the new course shell

```bash
moosh -p <webroot> -n course-create --fullname="New Course Full Name" --shortname="NEW_SHORTNAME" --category=CATEGORY_ID
```

### Step 4: Restore into the new course

```bash
moosh -p <webroot> -n course-restore /tmp/COURSE_TEMPLATE.mbz TARGET_CATEGORY_ID
```

### Step 5: Rename if needed

If the restored course has a different shortname than desired:
```bash
moosh -p <webroot> -n course-mod --id=NEW_COURSE_ID --shortname=NEW_SHORTNAME --fullname="New Name"
```

### Step 6: Clear cache

```bash
moosh -p <webroot> -n cache-clear
```

## Post-Restore Checklist

After a successful restore, verify:

1. **Code Runner prototypes exist** — use `moosh php-eval` to check `get_prototype()` returns `true`. If missing, import them (see `coderunner-prototype-import`). **Best practice**: move prototypes to course-level categories so future backups include them automatically.

2. **Math rendering** — the legacy TeX filter is disabled in Moodle 5.x. Questions using `$...$` inline delimiters won't render. **Cloned questions inherit the same broken delimiters**, so both source and clone need fixing. See `moodle-math-delimiter-fix` skill.

3. **No enrolments leaked** — verify with the query below.

## Pitfalls

1. **System-level prototypes are NOT included in template backups.** Move them to course-level categories for backup safety (see `coderunner-prototype-import` → "Best Practice: Course-Level Prototypes").

2. **`--template` is the key flag.** Without it, user data may be included. With it, enrolments, grades, and user content are excluded.

3. **Moosh needs `--moodle-path` (`-p`)** — the Moodle installation root (e.g., `<webroot>`).

4. **Moosh needs `--no-user-check` (`-n`)** — skips ownership verification, which fails in containerized environments.

5. **Slow backups.** Large courses (100+ activities, 1000+ questions) can take 5-15 minutes for CLI backup.

6. **The `moosh course-backup` may hang silently** if Moodle's PHP-FPM has issues. Watch with `ps aux | grep php-fpm` and check `/tmp/` for the `.mbz` file.

7. **Restore creates a new course** in the target category. The course ID is assigned automatically.

## Verifying the clone

```bash
# Check the new course exists
moosh sql-run "SELECT id, shortname, fullname FROM mdl_course WHERE shortname = 'NEW_SHORTNAME'"

# Verify no enrolments leaked over
moosh sql-run "SELECT COUNT(*) AS enrolments FROM mdl_user_enrolments ue JOIN mdl_enrol e ON ue.enrolid = e.id WHERE e.courseid = NEW_COURSE_ID"

# Verify question count matches source
moosh sql-run "SELECT COUNT(*) AS questions FROM mdl_question q JOIN mdl_question_bank_entries qbe ON qbe.id = qv.questionbankentryid JOIN mdl_question_versions qv ON qv.questionid = q.id JOIN mdl_question_categories qc ON qc.id = qbe.questioncategoryid WHERE qc.contextid IN (SELECT id FROM mdl_context WHERE contextlevel=70 AND instanceid=NEW_COURSE_ID)"
```
