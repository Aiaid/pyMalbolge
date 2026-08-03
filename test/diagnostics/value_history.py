"""Reconstruct the full value history of chosen memory cells -- finding I7.

`write_trace` answers "who wrote this cell", which was enough to find the
death mechanism in §I2 and §I7 but not enough to explain either. In Malbolge a
cell's value changes on three occasions:

    init      the assembled image, or the crazy-fill rule for cells past it
    write     a `rotr [d]` or `crz [d], a` naming it as the destination
    encrypt   the ENCRYPT substitution applied to a cell *after it executes*

Only the middle one is a write. A cell nobody ever writes still changes every
time it is run, so a writer list cannot say what a cell held before a write, or
whether it ever held legal code at all. That is exactly the question §I7 was
left with: the bootstrap wrote 0 into a cell it later executed, and it is
undecided whether

    (A) the cell was legal code and the write destroyed it, or
    (B) the write was normal (that region is meant to be data) and the defect
        is that control flow arrived there at all.

This module records the whole chain. Per observed address it reports every
valuation with its cause, whether the cell was ever executed, and whether each
valuation was a legal instruction character (33..126).

    history(mb, addrs, mc)      value history of `addrs`, plus optional
                                writer-pc detail and an approach trace
    format_report(rep)          render it

    python -m test.diagnostics.value_history d1.mb d1.mc --addr 4769119 \
        --pc 4698336 --tail 40

Observation alone cannot close the A/B question, because both stories predict
the same event chain. Two interventions can, and they are here for that:

    repair(mb, {(step, addr): value})   undo one write's effect on memory
    patch_source(mb, {addr: char})      change one cell of the image, then run
                                        it through the ordinary path

A story that says "this write is the defect" predicts that removing it yields
a correct program. That prediction is falsifiable and cheap, which is the only
reason to trust the story -- see findings §I7's methodological note. It was
worth running: the answer is (A), but undoing the write does *not* fix the
program, because it is one of 32 such writes. `evidence/i7-value-history.txt`
has the capture.

Runs are slow (pure Python, millions of steps); one pass covers any number of
addresses, so ask for everything at once.
"""

import argparse
import collections
import sys

from malbolge.core import OPS_VALID
from malbolge.malbolge20 import crazy20

from .layout_tool import layout_map, whereis
from .traced_run import run

#: One valuation of one cell. `kind` is 'init', 'write' or 'encrypt'; `pc` is
#: the instruction responsible (None for 'init', the writer's C for 'write',
#: and the cell's own address for 'encrypt', since ENCRYPT only ever rewrites
#: the cell that just executed). `info` carries measured extras -- for 'write',
#: the A register the write was computed from.
Event = collections.namedtuple('Event', 'step kind pc old new info')
Event.__new__.__defaults__ = (None,)

#: `events` is the chain above; `execs` is [(step, decoded_v), ...] for every
#: time the cell was executed as an instruction. A cell can be written without
#: ever running (pure data) or run without ever being written (pure code); the
#: two lists together are what distinguishes those cases.
CellHistory = collections.namedtuple(
    'CellHistory', 'addr where init final events execs')

Report = collections.namedtuple('Report', 'cells pc_execs tail run')


def legal(value):
    """True if `value` decodes to an instruction (the interpreter's test)."""
    return value is not None and 33 <= value <= 126


def history(mb_text, addrs, mc_text=None, input_data="", max_steps=None,
            watch_pcs=(), tail=0, tail_until=None):
    """Record the value history of `addrs` in one run.

    `watch_pcs` additionally reports every execution at those addresses with
    the register state and the memory operand the instruction saw, which is
    what identifies a writer. `tail` keeps the last N executed addresses, so
    the approach to a crash can be read as a march or a jump; `tail_until`
    freezes that buffer at a chosen step instead of at the halt, which is how
    a passing program is asked what *it* was doing at the moment its failing
    sibling died.

    Returns a Report. `run` is the RunResult as a dict, the same shape
    `write_trace` reports.
    """
    addrs = set(addrs)
    pcs = set(watch_pcs)
    lm = layout_map(mc_text) if mc_text is not None else None

    init = {}
    shadow = {}
    events = {a: [] for a in addrs}
    execs = {a: [] for a in addrs}
    pc_execs = []
    tailbuf = collections.deque(maxlen=tail) if tail else None
    memref = []
    # Last register state seen, so a write can report the A it consumed: `crz`
    # assigns the result to A, so by the time on_write fires the operand is
    # gone.
    regs = [0, 0, 0]

    def on_load(mem):
        memref.append(mem)
        for a in addrs:
            init[a] = shadow[a] = mem[a]
            events[a].append(Event(-1, 'init', None, None, mem[a]))

    def on_regs(step, a, c, d):
        regs[0] = a
        if c in pcs:
            # Read the operands before the instruction runs: mem[d] is what
            # this instruction is about to consume or overwrite, and mem[c] is
            # still pre-ENCRYPT, so `v` here is the opcode that dispatched.
            mem = memref[0]
            mem_c = mem[c]
            pc_execs.append({'step': step, 'pc': c, 'a': a, 'd': d,
                             'mem_c': mem_c, 'v': (mem_c + c) % 94,
                             'mem_d': mem[d]})

    def on_exec(step, c, v):
        if c in addrs:
            execs[c].append((step, v))
        if tailbuf is not None and (tail_until is None or step <= tail_until):
            tailbuf.append((step, c, v))

    def on_write(step, c, d, value):
        if d in addrs:
            old = shadow[d]
            shadow[d] = value
            events[d].append(Event(step, 'write', c, old, value,
                                   {'a_before': regs[0]}))

    def on_encrypt(step, c, old, new):
        if c in addrs:
            shadow[c] = new
            events[c].append(Event(step, 'encrypt', c, old, new))

    result = run(mb_text, input_data=input_data, on_load=on_load,
                 on_exec=on_exec, on_regs=on_regs, on_write=on_write,
                 on_encrypt=on_encrypt, max_steps=max_steps)

    cells = {}
    for a in sorted(addrs):
        cells[a] = CellHistory(
            addr=a,
            where=whereis(lm, a) if lm is not None else None,
            init=init.get(a),
            final=shadow.get(a),
            events=events[a],
            execs=execs[a],
        )
    if lm is not None:
        for rec in pc_execs:
            rec['where'] = whereis(lm, rec['pc'])
    return Report(cells=cells, pc_execs=pc_execs,
                  tail=list(tailbuf) if tailbuf else [],
                  run=dict(result._asdict()))


def crz_operands(a, mem_d):
    """The value `crz [d], a` produces from these operands (for cross-checks)."""
    return crazy20(a, mem_d)


def repair(mb_text, repairs, input_data="", max_steps=None):
    """Re-run with chosen writes undone, and report what changes.

    `repairs` maps (step, addr) -> value: when that write happens, the cell is
    put back to `value` immediately afterwards. Everything else runs normally.

    The intervention is deliberately minimal, and incomplete in one known way:
    `rotr` and `crz` assign the result to A as well as to memory, and A is not
    restored. So a repair that fixes the program proves the memory corruption
    was the fatal effect; a repair that does not is inconclusive, because the
    surviving A perturbation is a second difference. `patch_source` is the
    complete counterfactual when the answer has to be unambiguous.

    Returns (RunResult-as-dict, applied) where `applied` lists the repairs that
    actually fired.
    """
    memref = []
    applied = []

    def on_load(mem):
        memref.append(mem)

    def on_write(step, c, d, value):
        want = repairs.get((step, d))
        if want is not None:
            memref[0][d] = want
            applied.append((step, c, d, value, want))

    result = run(mb_text, input_data=input_data, on_load=on_load,
                 on_write=on_write, max_steps=max_steps)
    return dict(result._asdict()), applied


def patch_source(mb_text, patches):
    """Return `mb_text` with `patches` ({addr: char or int}) applied.

    The .mb images this project produces carry no whitespace, so a cell's
    address is its string index; the assertion guards that. Each replacement
    is checked against the interpreter's legality rule at its own address,
    since a character is only an instruction relative to where it sits.
    """
    assert not any(ch in mb_text for ch in ' \n\r\t'), (
        'patch_source assumes address == string index; this image has '
        'whitespace and would need parse_source-based indexing')
    out = list(mb_text)
    for addr, ch in patches.items():
        if isinstance(ch, int):
            ch = chr(ch)
        v = (ord(ch) + addr) % 94
        assert v in OPS_VALID, (
            'patched cell %d would decode to %d, which is not an instruction'
            % (addr, v))
        out[addr] = ch
    return ''.join(out)


def is_march(tail, window=None):
    """Classify an approach trace: consecutive C means a linear march.

    Returns (steps_examined, number_of_non_consecutive_hops). A bootstrap that
    walked onto a cell has zero hops; one that jumped there has at least one.
    """
    seq = tail if window is None else tail[-window:]
    hops = 0
    for (s1, c1, _v1), (s2, c2, _v2) in zip(seq, seq[1:]):
        if c2 != c1 + 1 or s2 != s1 + 1:
            hops += 1
    return len(seq), hops


def format_cell(cell, max_events=40):
    lines = ['cell %d%s' % (cell.addr,
                            '  -- %s' % cell.where if cell.where else '')]
    lines.append('  init %s (%s)' % (
        cell.init, 'legal' if legal(cell.init) else 'ILLEGAL'))
    lines.append('  executed %d time(s)%s' % (
        len(cell.execs),
        '' if not cell.execs else '; first step %d, last step %d'
        % (cell.execs[0][0], cell.execs[-1][0])))
    lines.append('  %d valuation event(s):' % len(cell.events))
    shown = cell.events[:max_events]
    for e in shown:
        extra = ''
        if e.kind == 'write' and e.info:
            extra = '  a_before=%s' % e.info.get('a_before')
        lines.append('    step %-12s %-8s pc %-12s %s -> %-4s %-8s%s' % (
            e.step if e.step >= 0 else '-', e.kind,
            e.pc if e.pc is not None else '-',
            e.old if e.old is not None else '-', e.new,
            'legal' if legal(e.new) else 'ILLEGAL', extra))
    if len(cell.events) > len(shown):
        lines.append('    ... %d more' % (len(cell.events) - len(shown)))
    lines.append('  final %s (%s)' % (
        cell.final, 'legal' if legal(cell.final) else 'ILLEGAL'))
    return lines


def format_report(rep, max_events=40, tail_show=20):
    lines = ['run: %s' % rep.run, '']
    for addr in sorted(rep.cells):
        lines += format_cell(rep.cells[addr], max_events)
        lines.append('')
    if rep.pc_execs:
        lines.append('watched pcs (%d execution(s)):' % len(rep.pc_execs))
        for rec in rep.pc_execs[:max_events]:
            lines.append('  step %-12d pc %-12d v=%-3d mem[c]=%-4d a=%-12d '
                         'd=%-12d mem[d]=%-6s  %s'
                         % (rec['step'], rec['pc'], rec['v'], rec['mem_c'],
                            rec['a'], rec['d'], rec['mem_d'],
                            rec.get('where') or ''))
        lines.append('')
    if rep.tail:
        n, hops = is_march(rep.tail)
        lines.append('approach trace: last %d executed cells, %d non-'
                     'consecutive hop(s)' % (n, hops))
        for step, c, v in rep.tail[-tail_show:]:
            lines.append('  step %-12d c %-12d v %d' % (step, c, v))
    return '\n'.join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('mb')
    p.add_argument('mc', nargs='?', default=None)
    p.add_argument('--addr', type=int, nargs='+', required=True)
    p.add_argument('--pc', type=int, nargs='*', default=[])
    p.add_argument('--tail', type=int, default=0)
    p.add_argument('--tail-until', type=int, default=None,
                   help='freeze the approach trace at this step instead of '
                        'at the halt')
    p.add_argument('--input', default='')
    p.add_argument('--max-steps', type=int, default=None)
    args = p.parse_args(argv)

    def load(path):
        with open(path) as f:
            return f.read()

    mc = load(args.mc) if args.mc else None
    rep = history(load(args.mb), args.addr, mc, input_data=args.input,
                  max_steps=args.max_steps, watch_pcs=args.pc, tail=args.tail,
                  tail_until=args.tail_until)
    print(format_report(rep))
    return 0


if __name__ == '__main__':
    sys.exit(main())
