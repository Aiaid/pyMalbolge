"""The two falsified size-optimization transforms, kept reproducible.

Findings I2 and I3 are negative results, and a negative result is only worth
anything if the counterexample can be re-run. Neither transform is part of the
compiler -- both are wrong -- so they live here, applied on top of the shipped
mc2mb rather than inside it. The shipped path stays byte-exact against the
reference toolchain; nothing in this module runs unless a diagnostic calls it.

Option one (`option_one`, falsified in I2)
    A `FLAG 1/2` costs ~39,950 B because a nonzero initial value has no legal
    instruction character under xlat1, so the whole page is pushed into the
    indirect region and constructed at run time. A `FLAG 0/2` costs ~38 B.
    The transform declares the flag 0/2 and inserts n `NEXT` at program entry
    to walk it to the intended state. foo went 1.06 MB -> 281 KB.

    Why it is wrong: flag state is advanced *jointly* by the ENCRYPT
    self-modification that follows execution and by the crazy writes NEXT
    performs, and `flag_cicle_addr`/`flag_cicle_value` were chosen for that
    joint orbit. A warm-up NEXT pushes the direct region's MOV_D byte off the
    designed orbit. The programs that passed did so because an orbit happened
    to close, not because the transform preserves semantics.

Option two (`option_two`, falsified in I3)
    Of the 79,900 B a pair of 1/2 flags costs, only ~5 KB is actually emitted;
    the rest is layout reservation, because `insNum_indir` reserves a flat 94
    words per indirect page regardless of how many cells that page uses.
    Reserving by actual cell count took the corpus to 0.12-0.26x.

    Why it is wrong: the reclaimed space is not padding. code_search's
    remote-write protocol returns through a cell adjacent to its target, so
    the reserved region carries a run-time navigation web. `fib(2)` with a
    while loop dies on a code cell that constant construction overwrote.

Usage:
    from test.diagnostics import optpatch
    mc2 = optpatch.option_one(mc_text)              # transform the .mc
    mb  = optpatch.assemble(mc2)                    # shipped assembler
    mb  = optpatch.assemble(mc_text, option_two=True)
"""

import pathlib
import re
import types

from malbolge.compiler import mc2mb

_MC2MB_PATH = (pathlib.Path(__file__).resolve().parents[2]
               / 'malbolge' / 'compiler' / 'mc2mb.py')

_FLAG_RE = re.compile(
    r'^FLAG\s+(\d+)\s*/\s*(\d+)\s*,\s*([A-Za-z]\w*)\s*$')


def option_one(mc_text, flags=None):
    """Rewrite `FLAG n/d, NAME` to `FLAG 0/d` plus n entry NEXTs.

    `flags` limits the transform to a set of flag names; the I2 minimal
    counterexample is a single name, `{'FLAG10'}`, on a program with one
    level of recursion. Passing None transforms every nonzero flag.
    """
    entry_routine = _program_entry_routine(mc_text)
    warmups = []
    out = []

    for line in mc_text.splitlines():
        m = _FLAG_RE.match(line.strip())
        if m:
            num, denom, name = int(m.group(1)), m.group(2), m.group(3)
            if num != 0 and (flags is None or name in flags):
                out.append('FLAG 0/%s, %s' % (denom, name))
                warmups.extend(['  NEXT %s' % name] * num)
                continue
        out.append(line)

    if not warmups:
        return mc_text
    return _insert_at_entry(out, entry_routine, warmups)


def _program_entry_routine(mc_text):
    m = re.search(r'^PROGRAM_START_TO\s+(\w+)@(\w+)\s*$', mc_text,
                  re.MULTILINE)
    if not m:
        raise ValueError('no PROGRAM_START_TO line: cannot locate entry')
    return m.group(2), m.group(1)


def _insert_at_entry(lines, entry, warmups):
    """Insert `warmups` immediately after `LABEL:` inside `ROUTINE NAME{`."""
    routine, label = entry
    in_routine = False
    out = []
    inserted = False
    for line in lines:
        out.append(line)
        stripped = line.strip()
        if stripped.startswith('ROUTINE '):
            in_routine = stripped.split()[1].rstrip('{') == routine
        elif in_routine and stripped == label + ':' and not inserted:
            out.extend(warmups)
            inserted = True
    if not inserted:
        raise ValueError('entry %s@%s not found' % (label, routine))
    return '\n'.join(out) + '\n'


# ---- option two: reserve indirect pages by actual cell count --------------
#
# The change is one line inside parse_mc_to_data, so it is applied the same
# way layout_tool reads the layout out: by re-executing a source-rewritten
# copy of the module. mc2mb.py itself is never modified.

_ORIGINAL_RESERVE = "    insNum_indir += (count_indir + 1) * 94"
_TIGHT_RESERVE = "    insNum_indir += sum(len(u) for u in UT_indir)"

_option_two_module = None


def _load_option_two():
    global _option_two_module
    if _option_two_module is None:
        src = _MC2MB_PATH.read_text()
        patched = src.replace(_ORIGINAL_RESERVE, _TIGHT_RESERVE)
        if patched == src:
            raise RuntimeError(
                'optpatch: the indirect reservation line moved in mc2mb.py; '
                'update _ORIGINAL_RESERVE')
        mod = types.ModuleType('mc2mb_option_two')
        exec(compile(patched, 'mc2mb_option_two.py', 'exec'), mod.__dict__)
        _option_two_module = mod
    return _option_two_module


def parse_to_data(mc_text, option_two=False):
    """`.mc` -> `.data`, optionally with option two's tighter reservation."""
    if option_two:
        return _load_option_two().parse_mc_to_data(mc_text)
    return mc2mb.parse_mc_to_data(mc_text)


def assemble(mc_text, option_two=False):
    """`.mc` -> `.mb`, optionally with option two's tighter reservation."""
    return mc2mb.data_to_mb(parse_to_data(mc_text, option_two=option_two))
