# Prototype Context Inspection and Troubleshooting

## Why a prototype may not be found even when the database is correct

Code Runner's `get_prototype()` calls a **private** `prototype_contexts()` method to determine which contexts to search. For Moodle 5.2+, this uses `question_bank_helper` and only searches:
1. The frontpage question bank context (contextid=12)
2. Question bank activity instances linked to the course

It does **NOT** automatically search the course-level question bank context (contextlevel=50).

### Inspecting searched contexts (reflection required)

The method is private, so use reflection:

```bash
moosh php-eval "
\$m = new ReflectionMethod('qtype_coderunner', 'prototype_contexts');
\$m->setAccessible(true);
\$ctx = context_course::instance(COURSE_ID);
echo implode(',', \$m->invoke(null, \$ctx));
"
```

If your prototype's category contextid is NOT in the returned list, move the category:

```bash
moosh sql-run "UPDATE mdl_question_categories SET contextid = SEARCHED_CONTEXT_ID WHERE id = YOUR_CATEGORY_ID"
```

## Moodle 5.x Math Rendering

The legacy TeX filter is **disabled** in Moodle 5.x (`active=-9999`). MathJax 3 is the renderer.

- `\( ... \)` for inline math — **use this**
- `$$ ... $$` for display math — **already works**
- `$ ... $` for inline math — **does NOT render** (legacy TeX filter disabled)

When converting questions:
- Replace `$var$` → `\(var\)`
- Leave `$$display$$` as-is

**Inside Twig templates** (Code Runner templates), double-escape: `\\(...\\)` because Twig processes the string first.

## Code Runner Upgrade Safety

Code Runner upgrades only delete built-in prototypes whose names start with `BUILTIN_PROTOTYPE_`:
```sql
WHERE q.name LIKE 'BUILT%IN_PROTOTYPE_%'
```
User-defined prototypes are never deleted by upgrades. The `CR_PROTOTYPES` category name is just a convention — `get_prototype()` filters by **contextid**, not category name.

## No conflict between same-named prototypes in different courses

Each course's `prototype_contexts()` returns an isolated set of context IDs. When course A looks for a prototype, it only sees prototypes in course A's contexts. Course B's prototype is invisible.
