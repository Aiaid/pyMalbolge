"""Replay mc2mb's layout computation and export the address map.

mc2mb decides, while parsing .mc, where every flag unit and routine lands in
the Malbolge20 address space, but it keeps that map in locals and emits only
the .data text. This module re-executes `parse_mc_to_data` with an export hook
injected before the emit step, so the map can be recovered without changing
the shipped compiler (whose byte-exactness against the reference toolchain is
the property the whole test suite defends).

Usage:
    from test.diagnostics.layout_tool import layout_map, whereis
    lm = layout_map(mc_text)
    lm['flags']['FLAG10']       # ('dir'|'indir', absolute address)
    whereis(lm, 10_800_123)     # '<structure> (cell +1)' for a raw address
"""

import pathlib
import types

_MC2MB = (pathlib.Path(__file__).resolve().parents[2]
          / 'malbolge' / 'compiler' / 'mc2mb.py')

_SRC = _MC2MB.read_text()

# The hook goes in immediately before .data emission, at which point every
# layout table is final. Keep this anchor in sync with mc2mb.py.
_ANCHOR = "    # ---- emit .data ---------------------------------------------------"
_HOOK = '''
    import builtins as _b
    _b._LAYOUT = {
        'UT_label': dict(UT_label),
        'relateUT': dict(relateUT),
        'UT_dir_firstOffset': UT_dir_firstOffset,
        'UT_indir_firstOffset': UT_indir_firstOffset,
        'RT_firstOffset': RT_firstOffset,
        'RT_offset': list(RT_offset),
        'RT_name': dict(RT_name),
        'RT_label': [dict(x) for x in RT_label],
    }
''' + _ANCHOR

_mod = types.ModuleType('mc2mb_layout')
_src2 = _SRC.replace(_ANCHOR, _HOOK)
assert _src2 != _SRC, (
    'layout_tool: anchor not found in mc2mb.py -- the emit marker moved, '
    'update _ANCHOR')
exec(compile(_src2, 'mc2mb_layout.py', 'exec'), _mod.__dict__)

# A unit occupies three consecutive cells, but only the base cell carries the
# decision: it decodes to MOV_D (40) when the flag reads ON and to a nop
# otherwise. Offset +1 is the jump that follows and always decodes to 4;
# offset +2 is never reached. `whereis` still resolves the whole span, since
# it is answering "what is near this address" rather than "is this a read".
UNIT_SPAN = 3
DECISION_OFFSET = 0


def layout_map(mc_text):
    """Return {'flags': {label: (area, addr)}, 'rt': {...}, 'meta': {...}}."""
    import builtins
    _mod.parse_mc_to_data(mc_text)
    L = builtins._LAYOUT
    flags = {}
    for label, (ua, ub) in L['UT_label'].items():
        c, dpage = L['relateUT'].get(ua, (0, -1))
        if c == 1:
            addr = L['UT_dir_firstOffset'] + dpage * 94 + ub
        elif c == -1:
            addr = L['UT_indir_firstOffset'] + dpage * 94 + ub
        else:
            addr = None
        flags[label] = ('dir' if c == 1 else 'indir', addr)
    rts = {}
    for name, i in L['RT_name'].items():
        rts[name] = (L['RT_offset'][i], L['RT_label'][i])
    return {'flags': flags, 'rt': rts, 'meta': {k: L[k] for k in
            ('UT_dir_firstOffset', 'UT_indir_firstOffset', 'RT_firstOffset')}}


def cell_owners(lm):
    """Return {decision address: unit label} for every unit.

    This is the lookup the flag tracer needs: it has to classify each executed
    address, not search a list per step. Only the decision cell is mapped, so
    one visit to a unit yields exactly one event.

    Note that `UT_label` covers every unit, not only flags -- shared
    structures such as ROT, OPR and SKIP appear here too, and they show up in
    the event stream as landmarks between flag reads.
    """
    owners = {}
    for label, (_area, addr) in lm['flags'].items():
        if addr is None:
            continue
        owners[addr + DECISION_OFFSET] = label
    return owners


def whereis(lm, addr):
    """Map an absolute address to a readable structure name."""
    for label, (area, a) in lm['flags'].items():
        if a is not None and abs(addr - a) <= 2:
            return f'{area}-unit {label} (cell {addr - a:+d})'
    for name, (off, labels) in lm['rt'].items():
        # labels: {label: relative address}
        rel = addr - off
        if 0 <= rel:
            near = sorted((ra, lb) for lb, ra in labels.items() if ra <= rel)
            if near and rel - near[-1][0] < 500:
                ra, lb = near[-1]
                return f'RT {name} @{lb}+{rel - ra}'
    return f'addr {addr} (unmapped)'
