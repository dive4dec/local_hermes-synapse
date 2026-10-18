#!/usr/bin/env python3
"""Harness: run every distinct coderunner model answer against its real test suite.

INPUT: /tmp/mock_midterms_data.json — shape:
  { "quizdefs": {qid: name}, "questions": [ {slot, maxmark, qid, name, qtype,
     questiontext, coderunner: {answer, answerpreload, globalextra, language, ...},
     tests: [ {testtype, display, mark, testcode, stdin, expected}, ... ],
     answers: [ {answer, fraction, feedback}, ... ]
     ] } ] }
  NOTE (Moodle 5.2): MCQ/match/ordering choices come from mdl_question_answers
  (column `question`, NOT `questionid`). `mdl_qtype_multichoice_options` is
  SETTINGS ONLY on 5.2 — reading choices from it yields answertext=None rows.
  Build the JSON with templates/extract_quiz_questions.php.

Semantics (see references/moodle52-schemas.md):
  - each test = fresh python process: decoded answer + '\n' + testcode
  - Scratchpad-JSON answers: join answer_code[]
  - Twig answers/templateparams: rendered with a dummy student (John / SMITH /
    john_smith@my.cityu.edu.hk)
  - combinator questions: order = testcode THEN answer (handle per-template)
  - grader: per-line rstrip; empty expected => pass iff rc==0 and stderr empty

OUTPUT: /tmp/mock_run_results.json + a per-question PASS/FAIL table.
Failures here are SUSPECTED bugs, not confirmed: re-run the specific question
by hand (rendering fully) before reporting, because incomplete Twig/JSON
rendering produces false failures.
"""
import json, subprocess, re, os, sys

PY = '/var/www/moodledata/.hermes/venv/bin/python3'
DATA = sys.argv[1] if len(sys.argv) > 1 else '/tmp/mock_midterms_data.json'
OUT = sys.argv[2] if len(sys.argv) > 2 else '/tmp/mock_run_results.json'
d = json.load(open(DATA))
qs = d['questions']

def clean(s):
    lines = [ln.rstrip() for ln in s.split('\n')]
    while lines and lines[-1] == '':
        lines.pop()
    return '\n'.join(lines)

DUMMY = {
    '{{ STUDENT.lastname ~ \' \' ~ STUDENT.firstname }}': 'SMITH John',
    '{{ STUDENT.lastname }}': 'SMITH',
    '{{ STUDENT.firstname }}': 'John',
    '{{ STUDENT.email }}': 'john_smith@my.cityu.edu.hk',
    '{{ firstname }}': 'John',
    '{{ lastname }}': 'SMITH',
    '{{ email }}': 'john_smith@my.cityu.edu.hk',
}
def twig(s):
    if not s:
        return s
    for a, b in DUMMY.items():
        s = s.replace(a, b)
    return s

def decode_answer(raw, is_json=False):
    code = raw or ''
    if is_json or code.lstrip().startswith('{'):
        try:
            j = json.loads(code)
            if isinstance(j, dict) and 'answer_code' in j:
                return ''.join(j['answer_code'])
        except Exception:
            pass
    return code

def run(script, stdin=''):
    try:
        p = subprocess.run([PY, '-I', '-c', script], input=stdin,
                           capture_output=True, text=True, timeout=30)
        return p.returncode, p.stdout, p.stderr, False
    except subprocess.TimeoutExpired as e:
        return 124, '', 'TIMEOUT after 30s', True

results = []
crs = {}
for r in qs:
    if r['qtype'] == 'coderunner':
        crs[r['qid']] = r   # distinct; first slot wins (identical across quizzes)

for qid, r in crs.items():
    cr = r['coderunner'] or {}
    is_json = bool(cr) and (cr.get('answer') or '').lstrip().startswith('{')
    base = (cr.get('globalextra') or '') + '\n' + twig(decode_answer(cr.get('answer'), is_json))
    qres = {'qid': qid, 'name': r['name'], 'maxmark': r['maxmark'], 'tests': []}
    for i, t in enumerate(r['tests']):
        script = base + '\n' + twig(t.get('testcode') or '')
        rc, out, err, to = run(script, twig(t.get('stdin') or ''))
        exp = twig(t.get('expected') or '')
        if exp.strip() != '':
            verdict = 'PASS' if clean(out) == clean(exp) else 'FAIL'
        else:
            verdict = 'PASS' if (rc == 0 and err.strip() == '') else 'FAIL'
        qres['tests'].append({
            'idx': i, 'display': t.get('display'), 'mark': t.get('mark'),
            'verdict': verdict, 'rc': rc, 'timeout': to,
            'got': out.strip()[:300], 'expected': exp.strip()[:300],
            'err_tail': (err.strip()[-400:] if verdict == 'FAIL' else ''),
        })
    results.append(qres)

json.dump(results, open(OUT, 'w'), indent=1, ensure_ascii=False)
npass = nfail = 0
print(f"{'QID':>6}  {'NAME':38}  {'TESTS':>9}  STATUS")
fails = []
for q in results:
    pf = sum(1 for x in q['tests'] if x['verdict'] == 'PASS')
    ff = len(q['tests']) - pf
    npass += pf; nfail += ff
    if ff:
        fails.append(q)
        flags = '; '.join(f"test{x['idx']+1}({x['display']})" for x in q['tests'] if x['verdict'] == 'FAIL')
        print(f"{q['qid']:>6}  {q['name'][:38]:38}  {pf}P/{ff}F   FAIL: {flags}")
    else:
        print(f"{q['qid']:>6}  {q['name'][:38]:38}  {pf}P/{ff}F   OK")
print(f"\nTOTAL: {npass} passed, {nfail} failed across {len(results)} questions")
print("SUSPECTED (verify before reporting):", [f"{q['name']} (qid {q['qid']})" for q in fails])
