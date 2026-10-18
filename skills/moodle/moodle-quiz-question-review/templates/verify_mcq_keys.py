#!/usr/bin/env python3
"""Verify a quiz's MULTICHOICE answer keys by evaluating every option in Python.

Companion to run_model_answers.py (CodeRunner). This one handles the MCQ /
statement / snippet options that make up the other half of an audit.

INPUT JSON shape (build with the extraction PHP; see SKILL.md §0 for the
deployed-version join — the qids in here MUST be the DEPLOYED versions):
  { "questions": [
      { "qid": int, "name": str, "qtype": "multichoice",
        "questiontext": str,
        "options": [ {"answer": str, "fraction": float, "feedback": str}, ... ] }
    ] }
  options order = mdl_question_answers `id ASC` (that is the display order).

USAGE:
  python3 verify_mcq_keys.py /tmp/quiz_data.json [qid qid ...]
  (no qid filter = check every multichoice question)

For each question it:
  - strips markdown from every option (``` fences, surrounding backticks)
  - dispatches eval (1-line expr) vs exec (snippet) on a per-option basis
  - binds the question's variables (set ENV below per question)
  - supports four "oracle" modes per question:
      expr_true     : option is correct iff eval(...) is True   (x,y,z / x=0 families)
      calls_eq1     : correct iff True AND a wrapped counter == 1 (short-circuit family)
      prints_match  : exec the snippet, compare captured stdout to a target
      compile_ok    : correct iff the statement compiles
      run_inputs    : exec with stdin lines, compare stdout to expected
  - reports stored-vs-computed per option and totals mismatches.

THE POINT IS DISCIPLINE, not cleverness: read "MISMATCH" lines, re-run the
single option by hand (print value / call-count / full stdout) BEFORE
believing it. Every false alarm in the E-Quiz 3/4 sessions was a harness
artifact (unstripped backticks, eval on a snippet, missing env var,
space-separated stdin, crash-misread-as-non-infinite) — see SKILL.md
"Verifying MCQ answer keys in Python — harness pitfalls".

Oracle wiring is INTENTIONALLY explicit: you must read the stem and choose the
oracle + env for each question. There is no auto-detection — guessing the
oracle is how you invent a false bug.
"""
import json, sys, io, re, subprocess, tempfile, os

PY = sys.executable or $DATA_DIR.'/.hermes/venv/bin/python3'


def clean_md(s: str) -> str:
    """Strip ``` fences and surrounding backticks; keep inner newlines."""
    c = re.sub(r'```[a-zA-Z]*', '', s)
    c = c.replace('```', '')
    c = c.strip()
    c = c.strip('`').strip()
    return c


def is_snippet(code: str) -> bool:
    # True when the option is a multi-line / block snippet (use run_snippet),
    # False for a one-line expression (use eval_option). The oracle kind you
    # wire still decides which path runs — this is only a convenience hint.
    block_kw = re.search(r'\b(if|else|elif|for|while|def)\b', code)
    if block_kw:
        return True
    if code.count('\n') > 1:
        return True
    if re.search(r'^[A-Za-z_]\w*\s*=\s*', code):
        return True
    return False


def make_counter(env):
    """Wrap env['check'] with a call counter (short-circuit family)."""
    calls = {'n': 0}
    orig = env.get('check')
    if orig is not None:
        def check(a, b, _o=orig, _c=calls):
            _c['n'] += 1
            return _o(a, b)
        env['check'] = check
    return calls


def run_snippet(code, env, stdin='', timeout=6):
    """Run a snippet in a FRESH subprocess (real CodeRunner semantics).

    NOTE: env vars do NOT carry into a subprocess — for snippet oracles that
    need variables (age, has_ticket, x=0, ...), either embed them in the code
    (prepend an `x = 0\n` line per option) or switch to in-process exec with
    redirect_stdout. For pure-input questions (stdin-driven) this is correct as
    is, because the question text itself declares the inputs.
    """
    with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False) as f:
        f.write(code)
        p = f.name
    try:
        r = subprocess.run([PY, '-I', p], input=stdin.encode(),
                           capture_output=True, timeout=timeout)
        return r.stdout.decode(), r.returncode, None
    except subprocess.TimeoutExpired:
        return '', None, 'TIMEOUT'
    finally:
        os.unlink(p)


def eval_option(expr, env):
    g = dict(env); g['__builtins__'] = __builtins__
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            v = eval(expr, g)
        return ('T' if bool(v) else 'F'), None
    except Exception as e:
        return ('ERR:' + type(e).__name__), None


def check_question(q, oracle):
    qid, name = q['qid'], q['name']
    kind = oracle['kind']
    env = dict(oracle.get('env', {}))
    print(f"=== qid {qid}  {name}   [{kind}]")
    mism = 0
    for i, o in enumerate(q['options']):
        stored = o['fraction'] > 0
        code = clean_md(o['answer'])
        if kind == 'expr_true':
            st, _ = eval_option(code, env)
            comp = (st == 'T')
        elif kind == 'calls_eq1':
            e2 = dict(env)
            calls = make_counter(e2)
            st, _ = eval_option(code, e2)
            comp = (st == 'T' and calls['n'] == 1)
            detail = f"(val={st}, calls={calls['n']})"
        elif kind == 'compile_ok':
            try:
                compile(code, '<t>', 'exec'); comp = True
            except SyntaxError:
                comp = False
        elif kind == 'prints_match':
            out, rc, err = run_snippet(code, env)
            comp = (err is None and out == oracle['expect'])
            detail = f"(out={out!r})"
        elif kind == 'run_inputs':
            out, rc, err = run_snippet(code, env,
                                       stdin=oracle.get('stdin', ''))
            comp = (err is None and out == oracle['expect'])
            detail = f"(out={out!r})"
        else:
            comp = None; detail = '(no oracle)'
        ok = (comp == stored) if comp is not None else True
        flag = '' if ok else '   <<< MISMATCH'
        if not ok:
            mism += 1
        detail = detail if kind in ('calls_eq1', 'prints_match', 'run_inputs') else ''
        print(f"   {chr(97+i)}) stored={'C' if stored else 'w'}({o['fraction']:+.2f}) "
              f"computed={'C' if comp else 'w'}  {code.replace(chr(10), ' ')[:54]} {detail}{flag}")
    print(("   -> all match" if mism == 0 else f"   -> {mism} MISMATCH") + "\n")
    return mism


# ---- ORACLE TABLE: read each stem and wire it explicitly -------------------
# kind: expr_true | calls_eq1 | compile_ok | prints_match | run_inputs
# For calls_eq1 you must supply the `check` function in env.
# For prints_match / run_inputs supply expect / stdin.
ORACLES = {
    # --- E-Quiz 3 style (short-circuit: check(a,b) with x,y,z bound) --------
    # Wire ONE of these per question; copy the stem's operator into check().
    # 'check(a,b): return a < b'  ->  'lambda a,b: a<b'
    # 'check(a,b): return a > b'  ->  'lambda a,b: a>b'
    # "which evaluate to True":        env x=5,y=10   kind expr_true
    # "True and call check exactly 1": kind calls_eq1
    # --- E-Quiz 4 style ------------------------------------------------------
    # "print 1,2,3 on separate lines": kind prints_match expect="1\n2\n3\n"
    # "sum 1..100":                    kind run_inputs stdin="" expect="5050\n"
    # "which loops are infinite":      needs a TIMEOUT oracle (extend: treat
    #     TimeoutExpired as the True case) — see SKILL.md pitfall 5.
    # "statements about range()":      kind expr_true on the range(...)==[...] claim
    # "for-else / count negatives":    kind run_inputs with NEWLINE-separated stdin
}
# To activate, populate ORACLES[qid] = {...} for the quiz you're auditing, e.g.:
# ORACLES[3627] = {'kind':'expr_true','env':{'x':5,'y':10}}
# ORACLES[3636] = {'kind':'calls_eq1','env':{'x':5,'y':10,'z':15,'check':lambda a,b:a<b}}
# ORACLES[3688] = {'kind':'prints_match','expect':'1\n2\n3\n'}
# ORACLES[3752] = {'kind':'run_inputs','stdin':'5\n0\n8\n-1\n','expect':'3\n'}


def main():
    data = sys.argv[1] if len(sys.argv) > 1 else '/tmp/quiz_data.json'
    only = set(map(int, sys.argv[2:])) if len(sys.argv) > 2 else None
    d = json.load(open(data))
    total = 0
    for q in d['questions']:
        if q.get('qtype') != 'multichoice':
            continue
        qid = int(q['qid'])
        if only is not None and qid not in only:
            continue
        oracle = ORACLES.get(qid)
        if oracle is None:
            print(f"=== qid {qid}  {q['name']}   [NO ORACLE WIRING — skipped]\n")
            continue
        total += check_question(q, oracle)
    print("TOTAL MCQ mismatches:", total)


if __name__ == '__main__':
    main()
