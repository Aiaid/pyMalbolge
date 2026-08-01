"""Record and diff flag event streams -- the instrument behind finding I2.

A "flag event" is the moment execution reaches a cell belonging to a flag unit.
What is recorded is the *decoded* opcode at that cell, `v = (mem[c] + c) % 94`,
because that is what the flag means at run time:

    v == 40   MOV_D    the dispatch jump is taken   -- flag reads ON
    other              execution falls through      -- flag reads OFF

Events are keyed by flag *label*, not by address, which is what makes two
builds comparable: a layout transform moves a flag to a different address but
keeps its .mc label, so the label streams of two variants of the same program
line up event for event until their behaviour actually diverges.

That is the whole argument of finding I2. Option one (declare a 1/2 flag as
0/2 and warm it up with an entry NEXT) produced a build that passed the entire
micro-test matrix, the nagoya corpus and a 326-flag scaling sweep -- and then
read one flag the wrong way round on a recursive program. The two streams are
identical for 6931 events; at 6931 the baseline reads FLAG10 as 40 (ON) and
the transformed build reads 44 (OFF), walks past its return target down the
linear dispatch chain, and dies 45 events later. See
`evidence/i2-flag-divergence.txt` for that window, captured from the original
run.

Usage:
    from test.diagnostics.flag_trace import record, first_divergence
    base = record(open('base.mb').read(), open('base.mc').read())
    var  = record(open('var.mb').read(),  open('var.mc').read())
    first_divergence(base, var)

    python -m test.diagnostics.flag_trace base.mb base.mc var.mb var.mc
"""

import argparse
import sys

from .layout_tool import cell_owners, layout_map
from .traced_run import run

MOV_D = 40  # decoded opcode meaning "flag is ON"


def record(mb_text, mc_text, input_data="", max_steps=None, max_events=None):
    """Return [(flag_label, decoded_v, step), ...] for one program run.

    `mc_text` is the .mc the .mb was assembled from; it supplies the layout
    map that says which addresses belong to which flag.
    """
    owners = cell_owners(layout_map(mc_text))
    events = []

    def on_exec(step, c, v):
        label = owners.get(c)
        if label is not None:
            events.append((label, v, step))
            if max_events is not None and len(events) >= max_events:
                raise _Enough()

    try:
        result = run(mb_text, input_data=input_data, on_exec=on_exec,
                     max_steps=max_steps)
    except _Enough:
        return events, {'output': '', 'steps': -1, 'reason': 'max_events',
                        'addr': None}
    return events, dict(result._asdict())


class _Enough(Exception):
    pass


def first_divergence(a, b):
    """Index of the first event where two streams disagree on (label, value).

    Steps are ignored: a layout transform shifts absolute step counts even
    where behaviour is identical, so only the flag *decision* sequence is
    compared. Returns None if one stream is a prefix of the other.
    """
    for i in range(min(len(a), len(b))):
        if a[i][:2] != b[i][:2]:
            return i
    return None


def format_window(a, b, index, radius=10):
    """Render the events around `index` from both streams, side by side."""
    lines = ['# columns: index | baseline (unit, decoded_v, step) '
             '| variant (unit, decoded_v, step)', '']
    for i in range(max(0, index - radius), index + radius + 1):
        ea = a[i] if i < len(a) else None
        eb = b[i] if i < len(b) else None
        mark = '  <== DIVERGES' if (ea and eb and ea[:2] != eb[:2]) else ''
        lines.append('%5d | %-22s %3s %10s | %-22s %3s %10s%s' % (
            i,
            ea[0] if ea else '-', ea[1] if ea else '-', ea[2] if ea else '-',
            eb[0] if eb else '-', eb[1] if eb else '-', eb[2] if eb else '-',
            mark))
    return '\n'.join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('base_mb')
    p.add_argument('base_mc')
    p.add_argument('var_mb')
    p.add_argument('var_mc')
    p.add_argument('--input', default='')
    p.add_argument('--max-steps', type=int, default=None)
    p.add_argument('--radius', type=int, default=10)
    args = p.parse_args(argv)

    def load(path):
        with open(path) as f:
            return f.read()

    base, base_info = record(load(args.base_mb), load(args.base_mc),
                             args.input, args.max_steps)
    var, var_info = record(load(args.var_mb), load(args.var_mc),
                           args.input, args.max_steps)
    print('baseline: %d events, %s' % (len(base), base_info))
    print('variant:  %d events, %s' % (len(var), var_info))

    i = first_divergence(base, var)
    if i is None:
        print('no divergence in the common prefix (%d events)'
              % min(len(base), len(var)))
        return 0
    print('\nfirst divergence at event %d\n' % i)
    print(format_window(base, var, i, args.radius))
    return 1


if __name__ == '__main__':
    sys.exit(main())
