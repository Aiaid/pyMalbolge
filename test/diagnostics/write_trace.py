"""Trace runtime writes that land outside their intended region -- finding I3.

Option two (reserve indirect pages by actual cell count instead of a flat 94
words per page) shrank the corpus to 0.12-0.26x and passed single recursion
and loop-free fib, then failed on `fib(2)` with a while loop. The failure mode
is not an assembler error: the build is well-formed and runs for millions of
steps, then reaches one of its *own* code cells and finds it holding a value
no instruction decodes to.

Something overwrote code at run time. Finding that something is a
who-wrote-this-cell question, which is what this module answers:

    culprit(mb, mc)   run until the illegal-instruction halt, then re-run and
                      report every write that hit the cell it died on

The answer in the I3 case was constant construction -- var_generate's
ROT/CON2/PAT accumulation, which should land in the data module M_DATA --
writing megabytes away instead. The reserved space that option two reclaimed
as "pure padding" in fact carries the navigation web that code_search's
remote-write protocol walks: M_LODX loads the target pointer, 'j' jumps out,
'p' writes, and the return hop reads a cell *adjacent to the target*. Tighten
the reservation and the return hop lands somewhere undefined.

Usage:
    from test.diagnostics.write_trace import culprit, watch
    culprit(open('fib2.mb').read(), open('fib2.mc').read())
    watch(mb, mc, addrs=[10_800_000])

    python -m test.diagnostics.write_trace fib2.mb fib2.mc
"""

import argparse
import sys

from .layout_tool import layout_map, whereis
from .traced_run import run


def regions(lm):
    """Region boundaries, low to high, as (name, first_address) pairs."""
    m = lm['meta']
    return [
        ('data module / bootstrap', 0),
        ('indirect units', m['UT_indir_firstOffset']),
        ('direct units', m['UT_dir_firstOffset']),
        ('routines', m['RT_firstOffset']),
    ]


def classify(lm, addr):
    """Name the region an address falls in."""
    name = 'below data module'
    for label, first in regions(lm):
        if addr >= first:
            name = label
    return name


def watch(mb_text, mc_text, addrs, input_data="", max_steps=None):
    """Report every runtime write to any address in `addrs`.

    Returns [(step, writer_pc, target, value, writer_location), ...].
    """
    lm = layout_map(mc_text)
    targets = set(addrs)
    hits = []

    def on_write(step, c, d, value):
        if d in targets:
            hits.append((step, c, d, value, whereis(lm, c)))

    result = run(mb_text, input_data=input_data, on_write=on_write,
                 max_steps=max_steps)
    return hits, dict(result._asdict())


def culprit(mb_text, mc_text, input_data="", max_steps=None):
    """Two-pass root cause for an illegal-instruction halt.

    Pass one runs to the halt and notes the address it died on. Pass two
    re-runs -- the interpreter is deterministic, so the run is identical --
    watching that one address, and returns the writes that hit it.

    Returns (report_dict, hits). `report_dict['reason']` is 'illegal' when the
    two-pass analysis applies; anything else means the program did not die the
    way this tool diagnoses, and `hits` is empty.
    """
    lm = layout_map(mc_text)

    result = run(mb_text, input_data=input_data, max_steps=max_steps)

    report = dict(result._asdict())
    if result.reason != 'illegal':
        return report, []

    # RunResult.addr is C at the moment the legality check failed. Do not try
    # to derive it from the previous instruction's address: a `jmp [d]` sets C
    # from memory, so "one past the last executed cell" is wrong precisely in
    # the case that matters -- a dispatch that jumped somewhere undefined.
    crash_addr = result.addr
    report['crash_addr'] = crash_addr
    report['crash_location'] = whereis(lm, crash_addr)
    report['crash_region'] = classify(lm, crash_addr)

    hits, _ = watch(mb_text, mc_text, [crash_addr], input_data, max_steps)
    return report, hits


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('mb')
    p.add_argument('mc')
    p.add_argument('--input', default='')
    p.add_argument('--max-steps', type=int, default=None)
    p.add_argument('--watch', type=int, nargs='*', default=None,
                   help='report writes to these addresses instead of running '
                        'the two-pass crash analysis')
    args = p.parse_args(argv)

    def load(path):
        with open(path) as f:
            return f.read()

    mb, mc = load(args.mb), load(args.mc)
    lm = layout_map(mc)
    print('layout: ' + ', '.join('%s @%d' % (n, a) for n, a in regions(lm)))

    if args.watch is not None:
        hits, info = watch(mb, mc, args.watch, args.input, args.max_steps)
        print('run: %s' % info)
        for step, c, d, value, where in hits:
            print('step %-12d pc %-12d wrote %-12d = %-12d  (pc in %s)'
                  % (step, c, d, value, where))
        return 0

    report, hits = culprit(mb, mc, args.input, args.max_steps)
    print('run: %s' % report)
    if report['reason'] != 'illegal':
        print('program did not halt on an illegal instruction; '
              'nothing to diagnose')
        return 0
    print('\ndied at %d -- %s (%s)' % (
        report['crash_addr'], report['crash_location'],
        report['crash_region']))
    if not hits:
        print('no runtime write hit that cell: the corruption is in the '
              'assembled image or in initialization, not in execution')
        return 1
    print('\nwrites that hit it:')
    for step, c, d, value, where in hits:
        print('  step %-12d pc %-12d = %-14d  (pc in %s)'
              % (step, c, value, where))
    return 1


if __name__ == '__main__':
    sys.exit(main())
