#!/usr/bin/env python3
"""Structural detectors for a quiz/question-bank review (run after extraction).

INPUT: same JSON as run_model_answers.py (/tmp/mock_midterms_data.json)
       plus an optional per-quiz entry map (see below) for bank-leakage.
CHECKS:
  1. Hidden Unicode (U+200B/200C/200D/FEFF/A0) in questiontext/answer/preload.
  2. Function-name consistency: text-specified `name(` vs def in answer/preload.
  3. Test-mark sums vs slot maxmark (hygiene only — CodeRunner auto-scales).
  4. Bank-leakage: shared questionbankentryid / questionid across quizzes
     (pass the entry list via /tmp/bank_entries.json: {qid: [entry,...]}).

Run: python3 detect_structure.py /tmp/mock_midterms_data.json
"""
import json, re, sys

DATA = sys.argv[1] if len(sys.argv) > 1 else '/tmp/mock_midterms_data.json'
BANK = '/tmp/bank_entries.json'
d = json.load(open(DATA))
qs = d['questions']

def decode_answer(raw):
    code = raw or ''
    try:
        j = json.loads(code)
        if isinstance(j, dict) and 'answer_code' in j:
            return ''.join(j['answer_code'])
    except Exception:
        pass
    return code

def defined_names(code):
    return set(re.findall(r'\bdef\s+([A-Za-z_]\w*)\s*\(', code or ''))

BUILTIN = {'print','range','len','int','float','str','input','abs','min','max','sum',
           'round','enumerate','zip','sorted','list','dict','set','tuple','isinstance',
           'open','map','filter','iter','next','format','any','all','ord','chr','hex',
           'oct','bin','id','hash','callable','eval','exec','compile','vars','dir',
           'help','exit','quit','repr','reversed','divmod','pow','bool','bytes',
           'bytearray','memoryview','frozenset','property','super','object','range'}

print("== 1. Hidden Unicode ==")
HID = {'\u200b':'ZWSP','\u200c':'ZWNJ','\u200d':'ZWJ','\ufeff':'BOM','\u00a0':'NBSP'}
for r in qs:
    for field in ('questiontext',):
        src = r.get(field) or ''
        for i, ch in enumerate(src):
            if ch in HID:
                print(f"  qid {r['qid']} {r['name']}: {HID[ch]} in {field} ...{src[max(0,i-20):i+20]!r}")
    cr = r.get('coderunner') or {}
    for f in ('answer', 'answerpreload'):
        src = cr.get(f) or ''
        for i, ch in enumerate(src):
            if ch in HID:
                print(f"  qid {r['qid']} {r['name']}: {HID[ch]} in {f} ...{src[max(0,i-20):i+20]!r}")

print("\n== 2. Function-name consistency (text vs answer vs preload) ==")
for r in qs:
    if r['qtype'] != 'coderunner':
        continue
    cr = r['coderunner'] or {}
    code = decode_answer(cr.get('answer'))
    pre = decode_answer(cr.get('answerpreload'))
    text = r.get('questiontext') or ''
    defn, predef = defined_names(code), defined_names(pre)
    fences = re.findall(r'```(.*?)```', text, re.S)
    spec = set()
    for f in fences:
        spec |= set(re.findall(r'\bdef\s+([A-Za-z_]\w*)\s*\(', f))
        for ln in f.splitlines():
            m = re.match(r'^\s*([A-Za-z_]\w*)\s*\([^)]*\)\s*(?:->|:|\{|$)', ln)
            if m and m.group(1) not in BUILTIN:
                spec.add(m.group(1))
    spec |= set(re.findall(r'`([A-Za-z_]\w*)\s*\(', text))
    spec = {s for s in spec if re.match(r'^[a-z][a-z0-9_]*$', s) and s not in BUILTIN}
    if spec and defn and not (spec & defn):
        print(f"  qid {r['qid']} {r['name']}: TEXT wants {sorted(spec)}, ANSWER defines {sorted(defn)}")
    if predef and defn and not (predef & defn):
        print(f"  qid {r['qid']} {r['name']}: PRELOAD defines {sorted(predef)}, ANSWER defines {sorted(defn)}")

print("\n== 3. Test-mark sums vs slot maxmark (hygiene) ==")
for r in qs:
    if r['qtype'] != 'coderunner':
        continue
    tsum = sum(t['mark'] for t in r.get('tests', []))
    if abs(tsum - r['maxmark']) > 1e-9:
        print(f"  qid {r['qid']} {r['name']}: slot maxmark {r['maxmark']}, tests sum {tsum} (delta {tsum-r['maxmark']:+.1f})")

print("\n== 4. Cross-quiz bank leakage ==")
try:
    bank = json.load(open(BANK))
    for a, la in bank.items():
        for b, lb in bank.items():
            if int(a) >= int(b):
                continue
            shared = set(map(int, la)) & set(map(int, lb))
            if shared:
                print(f"  quiz {a} & {b}: share {len(shared)}/{len(lb)} entries: {sorted(shared)}")
except FileNotFoundError:
    print("  (no /tmp/bank_entries.json — skip; extract via: per-quiz SELECT slot, questionbankentryid)")
