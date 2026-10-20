# Moodle 5.2 question-engine schemas & CodeRunner execution semantics

Verified on <moodle-host>, Moodle 5.2.1 (version 2026042001). The 5.2
question engine is **reworked** vs 3.x/4.x — several tables/columns are renamed
or absent. Do NOT guess; probe `information_schema.columns` first.

## The quiz → question mapping chain (5.2)

There is **NO** `mdl_quiz_questions` table and **NO** `mdl_question_question_usages`
table in this build. Questions attach to quiz slots via `mdl_question_references`:

```
mdl_quiz (id, course, name, grade, timelimit, timeopen, timeclose)
  → mdl_course_modules (instance = quiz id, module = modules.id for 'quiz')
  → mdl_quiz_slots (id, quizid, slot, maxmark, page)
  → mdl_question_references (itemid = quiz_slots.id, component='mod_quiz',
                             questionbankentryid, version)
  → mdl_question_bank_entries (id)
  → mdl_question_versions (questionbankentryid, version, questionid, status)
  → mdl_question (id, name, qtype, questiontext, questiontextformat, generalfeedback)
```

### Working join (CURRENT / DEPLOYED question text per quiz slot)
⚠️ `qr.version` is **NULL by design** on follow-latest references (the normal
state on this box) — a NULL there is NOT anomalous. The deployed version is the
reference's pinned `version`, else the entry's `MAX(version)`. A naive join
omits that filter and **fans each slot out to every version of its entry** —
that is how a 17-slot quiz "becomes" 50 rows and stale v1/v2 keys get audited
as live bugs (the E-Quiz 3 false-alarm root cause). Always filter:
```sql
SELECT s.quizid, s.slot, s.maxmark, qv.version AS deployed_version,
       qv.questionid, q.name, q.qtype, q.questiontext
FROM mdl_quiz_slots s
JOIN mdl_question_references qr ON qr.itemid = s.id AND qr.component='mod_quiz'
JOIN mdl_question_versions qv ON qv.questionbankentryid = qr.questionbankentryid
  AND qv.version = COALESCE(
        qr.version,
        (SELECT MAX(version) FROM mdl_question_versions
          WHERE questionbankentryid = qr.questionbankentryid))
JOIN mdl_question q ON q.id = qv.questionid
WHERE s.quizid = <quizid>
ORDER BY s.slot
```
Sanity check: **result row count must equal the quiz's `mdl_quiz_slots`
count** (1:1). More rows ⇒ fan-out ⇒ wrong version filter.
Notes:
- `qr.itemid` equals `mdl_quiz_slots.id` (NOT slot number, NOT quiz id).
- `mdl_question_usages` **DOES exist** (columns `id, contextid, component,
  preferredbehaviour`) — one row per quiz attempt, `component='mod_quiz'`,
  `contextid` = the quiz course-module's context (contextlevel=70,
  instanceid=cmid). Its `id` is the value stored in
  `mdl_question_attempts.questionusageid`, but it is NOT the same id space as
  `mdl_quiz_attempts.id` (don't join them on id). There is no
  `mdl_question_question_usages` table (that was the 3.x name).
  `mdl_question_attempts` has `questionusageid` + `questionid` + `minfraction`
  + `maxmark` (NO `mark` column) — earned marks = `minfraction * maxmark`.
- A question-bank entry can have MULTIPLE `question_versions`; the slot
  deploys the pinned `qr.version`, or — when `qr.version` is **NULL** (the
  normal follow-latest state, NOT a schema anomaly) — the entry's highest
  `question_versions.version`. See the COALESCE join above.
- One slot can list several versions in a naive join (all versions of an
  entry); that multiplies rows. ALWAYS pin to a single version (the COALESCE
  filter); do not merely `DISTINCT` — that only hides the symptom.

## mdl_question columns (5.2) — NOTE the format column name
`id, parent, name, questiontext, questiontextformat, generalfeedback,
generalfeedbackformat, defaultmark, penalty, qtype, length, stamp, timecreated,
timemodified, createdby, modifiedby`
- The format column is **`questiontextformat`** (NOT `questionformat`). Using the
  wrong name → "Error reading from database".
- `questiontextformat` values: 1=HTML, 2=Markdown, 4=Mobile, 5=Plain,
  6=Moodle-flavoured Markdown, 7=Plain. **Mobile(4) stores LaTeX with doubled
  backslashes** (`\\begin`) that render to single `\begin`. This is correct, not a bug.

## Question-type option storage (5.2) — the "options" tables are SETTINGS only

- `mdl_qtype_multichoice_options` = per-question SETTINGS (layout, single,
  shuffleanswers, answernumbering, the 3 feedback strings). It has NO
  `answertext`/`fraction`/`correct` columns.
- `mdl_qtype_match_subquestions` = the left-hand items (`questiontext`,
  `answertext` used as the correct-answer ref) PLUS settings columns.
- `mdl_qtype_match_options`, `mdl_qtype_ordering_options` = SETTINGS only.
- **The actual answer choices for MCQ, match, and ordering all live in
  `mdl_question_answers`** (`id, question, answer, answerformat, fraction,
  feedback, feedbackformat`) — same table CodeRunner-era Moodle used. `fraction`
  > 0 = correct, < 0 = wrong (multi-select sums to 1.0); for ordering the
  integer `fraction` encodes the correct position.

## CodeRunner (qtype_coderunner) option & test columns
`mdl_question_coderunner_options` (keyed by `questionid`): the interesting ones are
`answer`, `answerpreload`, `globalextra`, `language`, `template`,
`combinatortemplate`, `iscombinatortemplate`, `extractcodefromjson`, `twigall`,
`templateparams`, `templateparamslang`, `uiplugin`, `testsplitterre`,
`allowmultiplestdins`, `answerboxlines`.
- `mdl_question_coderunner_tests` (keyed by `questionid`): `testtype`
  (0=normal, 1=precheck, 2=both), `testcode`, `stdin`, `expected`, `extra`,
  `mark`, `display` (SHOW/HIDE), `useasexample`, `hiderestiffail`.
- Some coderunner questions have NO `coderunner_options` row (lazy creation /
  clones) — treat as "no options row", not an error.
- `mdl_question_hints` (keyed by `questionid`): `hint`, `hintformat`.

## Answer formats to decode before executing
| shape | how to detect | how to run |
|---|---|---|
| plain Python | no braces/JSON | run as-is |
| Scratchpad JSON | `{"answer_code":[...]}` | `json.loads`, join `answer_code`, run |
| Twig answer | contains `{{ STUDENT.` or `{{ firstname }}` | render named vars + STUDENT.* with a dummy student, run |
| Twig templateparams | `templateparams` JSON with `{{ ... }}` | render `templateparamslang=twig` to fill `{{ fix }}`/`{{ code }}` etc. |
| combinator | `iscombinatortemplate=1` | template iterates `TESTCASES`; order = **testcode THEN student answer** |

Dummy student for Twig rendering: firstname `John`, lastname `SMITH`,
email `<student-email>`. `STUDENT.lastname` is UPPERCASED by the
`|upper` filter in some questions — replicate that.

## EqualityGrader (default grader) exact rule
`qtype_coderunner_util::clean()` strips ALL trailing whitespace on every line
plus trailing whitespace at end of string (keeps blank lines mid-string). Then
byte-for-byte compare. So `3.0\n1.33984\n` == `3.0\n1.33984`. Empty expected ⇒
pass iff process exit 0 and stderr empty (assert-style tests).

## Cross-quiz / bank-leakage detector
To detect one quiz reusing another quiz's (or the live exam's) questions,
compare the **`questionbankentryid`** set per quiz (the stable bank identity),
and also the resolved `questionid` set:
```sql
-- per-quiz entry list
SELECT s.quizid, s.slot, qr.questionbankentryid
FROM mdl_quiz_slots s
JOIN mdl_question_references qr ON qr.itemid=s.id AND qr.component='mod_quiz'
WHERE s.quizid=<quizid> AND s.maxmark>0 ORDER BY s.slot;
```
8/8 shared entries between a mock and the real exam = full leak. A correct
makeup should share 0.

## Hidden-Unicode detector
Scan `questiontext` (and answer/preload) for U+200B, U+200C, U+200D, U+FEFF,
U+00A0. In-code U+200B inside a function signature is a real copy-paste hazard.
In prose `<p>\u00a0</p>` is usually a harmless spacer.

## Function-name consistency detector
Extract `def <name>` from the decoded answer code and from `answerpreload`;
extract `<name>(` from fenced code blocks and inline `` `name(` `` in the
question text. Flag when the text-specified set and the code-defined set don't
overlap (real mismatch, e.g. `wavelength` vs `calculate_wavelength`). Ignore
builtins and `math.isclose`-style dotted calls (split on the last `.`).
