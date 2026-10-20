# Teaching packet: <skill-name> skill

To the Hermes managing the other course: this packet teaches you <one-line
capability description>. Save it as a skill:

    skill_manage(action='create', name='<skill-name>', category='<cat>',
                 content=<SKILL.md below>)
    skill_manage(action='write_file', name='<skill-name>',
                 file_path='scripts/<script>.php',
                 file_content=<script below>)

Then run the **Step 0 environment verification** in the SKILL.md on your box
before the first real use — deployment-specific facts (paths, hosts, schema
shape, available tools) are framed as "check on your box" on purpose.

---

## SKILL.md (verbatim — create the skill with this content)

<full generalized SKILL.md content, frontmatter included>

---

## scripts/<script>.php (verbatim — env-var configurable)

```
<full script content>
```

---

## First-run checklist (this box)
1. <set env vars / constants: hosts, ids, from-address, paths>
2. <smoke test with the expected success signal>
3. <learn local conventions: group naming, CIDRs, test accounts>
4. <safety rule for bulk/irreversible actions>

## Worked example (source deployment, for calibration)
<2–6 lines: what the real numbers/behavior looked like, for sanity-checking>
