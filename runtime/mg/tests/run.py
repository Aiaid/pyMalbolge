#!/usr/bin/env python3
"""Compile every runtime/mg test + official template through the Nagoya
pipeline and run it on BOTH interpreters (pyMalbolge and the Nagoya C
reference), checking against expected output.

    python3 runtime/mg/tests/run.py [--py] [name ...]

By default only the (fast) C reference is run; pass --py to also run
pyMalbolge and assert py==C. Names filter which cases run.
"""
import os, subprocess, sys, tempfile, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
TERNARY   = os.path.join(ROOT, 'ref/nagoya-ternary/parser')
PARSE_MC2 = os.path.join(ROOT, 'ref/nagoya-lowass/parse_mc2.pl')
INIT      = os.path.join(ROOT, 'ref/nagoya-lowass/init/init')
CREF      = os.path.join(ROOT, 'ref/nagoya-malbolge20-interpreter/malbolge20')
HERE      = os.path.dirname(__file__)
OFFICIAL  = os.path.join(HERE, '..', 'official')

# name -> (mg_path, stdin, expected_bytes)
CASES = {
    't_read':          (f'{HERE}/t_read.mg',            b'', bytes([0xC8])),
    't_zero':          (f'{HERE}/t_zero.mg',            b'', bytes([0x00])),
    't_setc1':         (f'{HERE}/t_setc1.mg',           b'', bytes([0xC8])),
    't_mov':           (f'{HERE}/t_mov.mg',             b'', bytes([0xBF,0xBF,0x8D,0x37])),
    't_iszero_0':      (f'{HERE}/t_iszero_0.mg',        b'', b'Z'),
    't_iszero_1':      (f'{HERE}/t_iszero_1.mg',        b'', b'N'),
    't_iszero_59049':  (f'{HERE}/t_iszero_59049.mg',    b'', b'N'),
    'add':             (f'{OFFICIAL}/add.mg',           b'', bytes([12])),
    'sub':             (f'{OFFICIAL}/sub.mg',           b'', bytes([18])),
    'inc':             (f'{OFFICIAL}/inc.mg',           b'', b'A'),
    'dec':             (f'{OFFICIAL}/dec.mg',           b'', b'A'),
    'lt':              (f'{OFFICIAL}/lt.mg',             b'', b'Y'),
    'le':              (f'{OFFICIAL}/le.mg',             b'', b'Y'),
    'gt':              (f'{OFFICIAL}/gt.mg',             b'', b'Y'),
    'ge':              (f'{OFFICIAL}/ge.mg',             b'', b'Y'),
    'eq':              (f'{OFFICIAL}/eq.mg',             b'', b'Y'),
    'ne':              (f'{OFFICIAL}/ne.mg',             b'', b'Y'),
    'mul':             (f'{OFFICIAL}/mul.mg',            b'', bytes([42])),
    'div':             (f'{OFFICIAL}/div.mg',            b'', bytes([7])),
}


def compile_mg(mgpath):
    wd = tempfile.mkdtemp(); base = os.path.join(wd, 'p')
    mc, data, mb = base+'.mc', base+'.data', base+'.mb'
    r = subprocess.run([TERNARY, '-m', '-c', '-s', '1', mgpath],
                       stdout=open(mc, 'wb'), stderr=subprocess.PIPE, timeout=60)
    if r.returncode != 0:
        return None, 'ternary: ' + r.stderr.decode('utf-8', 'replace')
    subprocess.run(['perl', PARSE_MC2, mc, base], stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=60,
                   env=dict(os.environ, PERL_HASH_SEED='0'))
    if not os.path.exists(data):
        return None, 'parse_mc2 produced no .data'
    subprocess.run([INIT, data], stdout=open(mb, 'wb'), stderr=subprocess.DEVNULL, timeout=60)
    return mb, None


def run(mb, stdin, use_c, timeout=120):
    exe = [CREF, mb] if use_c else [sys.executable, '-m', 'malbolge', '--variant=malbolge20', mb]
    try:
        r = subprocess.run(exe, input=stdin, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, timeout=timeout, cwd=ROOT)
        return r.stdout
    except subprocess.TimeoutExpired:
        return b'<TIMEOUT>'


def main():
    args = sys.argv[1:]
    do_py = '--py' in args
    names = [a for a in args if not a.startswith('--')] or list(CASES)
    npass = nfail = 0
    for name in names:
        mgpath, stdin, expected = CASES[name]
        mb, err = compile_mg(mgpath)
        if mb is None:
            print(f'{name:16} COMPILE FAIL: {err}'); nfail += 1; continue
        t0 = time.time(); cout = run(mb, stdin, use_c=True); ct = time.time()-t0
        ok = (cout == expected)
        line = f'{name:16} C={cout!r} exp={expected!r} {"OK" if ok else "FAIL"} ({ct:.1f}s)'
        if do_py:
            pout = run(mb, stdin, use_c=False)
            ok = ok and (pout == cout)
            line += f'  py={pout!r} py==C={pout==cout}'
        print(line)
        npass += ok; nfail += (not ok)
    print(f'\n{npass} passed, {nfail} failed')
    sys.exit(1 if nfail else 0)


if __name__ == '__main__':
    main()
