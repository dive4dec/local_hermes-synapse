#!/usr/bin/env python3
"""
Bulk Code Runner question generator (copy + edit the QUESTIONS list, then run).

Flow: hold each question as data -> verify every answer+test in REAL Python
(venv python3) and ABORT on any failure -> emit a multi-question import XML
for the `qformat_xml` pipeline (see references/xml-import-recipe.md).

Usage:
    <venv>/bin/python3 gen_questions.py /tmp/batch.xml

DO NOT import the XML until this prints "0 failure(s)".
"""
import os, sys
from xml.sax.saxutils import escape

# Portable bootstrap (see skills/_conventions/PORTABLE.md). The CODE RUNNER PROTOTYPE name
# is course-specific — override via MHS_CODE_RUNNER_PROTOTYPE if your instance uses a different one.
WEBROOT = os.environ.get("MHS_WEBROOT", "/var/www/html/public")
RUNNER  = os.environ.get("MHS_CODE_RUNNER_PROTOTYPE", "python3_cs1302_prototype")

OUT_XML = sys.argv[1] if len(sys.argv) > 1 else "/tmp/batch.xml"
CATEGORY = "<coursecode> Exam 26//27 Sem A"   # EDIT per course/exam; literal '/' MUST be '//' in the path
RUNNER   = RUNNER                       # from MHS_CODE_RUNNER_PROTOTYPE (Sem-B prototype name)

# ---------------------------------------------------------------------------
# QUESTIONS — one entry per new question. testcases are strings of Python
# (assert-based Sem B style); first test = example/SHOW, rest SHOW then HIDE.
# Keep the model `answer` and every test mutually consistent.
# ---------------------------------------------------------------------------
QUESTIONS = [
    dict(
        name="example_question",
        qtext="Write a function `f(x)` that … (use `$$…$$` or `$x$` for math).",
        answer="def f(x):\n    return x + 1",
        tests=[
            'assert f(1) == 2',
            'assert f(-1) == 0\nassert f(0) == 1',
            'assert f(1302) == 1303',
        ],
    ),
    # … add more entries here …
]

# ---------------------------------------------------------------------------
# VERIFICATION — run every answer, then every test, in real Python. ABORT on
# any failure so a bad expected value never reaches the DB.
# ---------------------------------------------------------------------------
fail = 0
for spec in QUESTIONS:
    ns = {}
    try:
        exec(compile(spec["answer"], "<answer:%s>" % spec["name"], "exec"), ns)
    except Exception as e:
        print("FAIL(answer) %s: %s" % (spec["name"], e)); fail += 1; continue
    for tc in spec["tests"]:
        try:
            exec(compile(tc, "<test:%s>" % spec["name"], "exec"), ns)
        except Exception as e:
            print("FAIL(test) %s: %s: %s" % (spec["name"], e.__class__.__name__, e)); fail += 1

print("Verification: %d questions, %d failure(s)" % (len(QUESTIONS), fail))
if fail:
    sys.exit(1)

# ---------------------------------------------------------------------------
# XML EMISSION — one <quiz>, one category switch line, N coderunner questions.
# Every option field is explicit (import defaults do NOT match course style).
# ---------------------------------------------------------------------------
OPTION_FIELDS = {   # element -> value ('' = empty element)
    "prototypetype": "0", "allornothing": "0", "penaltyregime": "10, 20, ...",
    "precheck": "2", "hidecheck": "0", "showsource": "0",
    "answerboxlines": "18", "answerboxcolumns": "100",
    "answerpreload": "# YOUR CODE HERE", "globalextra": "",
    "validateonsave": "1", "templateparams": "", "hoisttemplateparams": "1",
    "extractcodefromjson": "1", "templateparamslang": "None",
    "templateparamsevalpertry": "0", "templateparamsevald": "{}",
    "twigall": "0", "uiparameters": "", "attachments": "0",
    "attachmentsrequired": "0", "maxfilesize": "10240", "filenamesregex": "",
    "filenamesexplain": "", "displayfeedback": "1", "giveupallowed": "0",
}
INHERIT_FIELDS = ["template", "iscombinatortemplate", "grader", "language",
                  "acelang", "sandbox", "sandboxparams", "cputimelimitsecs",
                  "memlimitmb", "uiplugin", "resultcolumns", "combinatortemplate",
                  "allowmultiplestdins", "testsplitterre", "perperttemplate",
                  "prototypeextra"]
# NOTE: leave INHERIT_FIELDS OUT of the XML entirely (they inherit from the
# prototype; the reference row stores them NULL). Do NOT write them as <x></x>.

p = ['<?xml version="1.0" encoding="UTF-8"?>\n<quiz>\n']
p.append('  <question type="category">\n    <category>\n      <text>%s</text>\n'
         '</category>\n  </question>\n' % escape(CATEGORY))
for spec in QUESTIONS:
    p.append('  <question type="coderunner">\n')
    p.append('    <name>\n      <text>%s</text>\n    </name>\n' % escape(spec["name"]))
    p.append('    <questiontext format="markdown">\n      <text>%s</text>\n'
             '</questiontext>\n' % escape(spec["qtext"]))
    p.append('    <generalfeedback format="markdown">\n      <text></text>\n'
             '</generalfeedback>\n')
    p.append('    <defaultgrade>1.0000000</defaultgrade>\n')
    p.append('    <penalty>0.0000000</penalty>\n')
    p.append('    <hidden>0</hidden>\n')
    p.append('    <idnumber></idnumber>\n')
    p.append('    <coderunnertype>%s</coderunnertype>\n' % RUNNER)
    for k, v in OPTION_FIELDS.items():
        p.append('    <%s>%s</%s>\n' % (k, escape(v), k))
    p.append('    <answer>%s</answer>\n' % escape(spec["answer"]))
    p.append('    <testcases>\n')
    for j, tc in enumerate(spec["tests"]):
        ex = 1 if j == 0 else 0
        disp = "SHOW" if j < 2 else "HIDE"
        p.append('      <testcase testtype="0" useasexample="%d" hiderestiffail="0" '
                 'mark="1.0000000">\n' % ex)
        p.append('        <testcode><text>%s</text></testcode>\n' % escape(tc))
        p.append('        <stdin><text></text></stdin>\n')
        p.append('        <expected><text></text></expected>\n')
        p.append('        <extra><text></text></extra>\n')
        p.append('        <display><text>%s</text></display>\n' % disp)
        p.append('      </testcase>\n')
    p.append('    </testcases>\n')
    p.append('  </question>\n')
p.append('</quiz>\n')
xml = "".join(p)
with open(OUT_XML, "w") as f:
    f.write(xml)
print("WROTE %s (%d bytes, %d questions)" % (OUT_XML, len(xml), len(QUESTIONS)))
