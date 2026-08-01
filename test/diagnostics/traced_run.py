"""An instrumented copy of the Malbolge20 interpreter loop.

`malbolge.malbolge20.eval` is a deliberately tight loop with no hooks, and it
should stay that way -- a per-step callback there would cost more than the
interpreter. So the diagnostics keep their own copy of the loop, structurally
identical to `malbolge20.eval` (same opcode dispatch, same ENCRYPT step, same
wraparound), with two observation points added:

    on_exec(step, c, v)          before every instruction dispatch
    on_write(step, c, d, value)  after every cell write (rotr / crz)

Both are optional; passing neither runs at roughly `eval`'s own speed. Keep
this loop in sync with `malbolge20.eval` -- if the two ever disagree, the
traces stop describing the interpreter under test.
"""

import collections

from malbolge.core import create_memory, parse_source
from malbolge.malbolge20 import (
    CONFIG, ENCRYPT, EOF_A, POW20, crazy20, rotate20,
)

#: `addr` is the value of C when the run stopped. For reason == 'illegal' that
#: is the cell holding the value no instruction decodes to -- the thing a
#: corruption hunt is looking for. It cannot be derived from the last executed
#: address, because a `jmp [d]` sets C from memory rather than advancing it.
RunResult = collections.namedtuple('RunResult', 'output steps reason addr')


def run(code, input_data="", eof='stop', on_exec=None, on_write=None,
        max_steps=None):
    """Run a Malbolge20 program with instrumentation.

    Returns a RunResult whose `reason` is one of 'illegal' (reached a cell
    outside legal program text), 'end' (v == 81), 'eof', or 'step_limit'.
    """
    mem = create_memory(CONFIG)
    mem.initialize_source(parse_source(code, CONFIG))

    output = []
    input_pos = 0
    a, c, d = 0, 0, 0
    mem_size = POW20
    step = 0

    while True:
        if max_steps is not None and step >= max_steps:
            return RunResult(''.join(output), step, 'step_limit', c)

        if mem[c] < 33 or mem[c] > 126:
            return RunResult(''.join(output), step, 'illegal', c)

        v = (mem[c] + c) % 94

        if on_exec is not None:
            on_exec(step, c, v)

        if v == 4:      # jmp [d]
            c = mem[d]
        elif v == 5:    # out a
            output.append(chr(int(a % 256)))
        elif v == 23:   # in a
            if input_pos >= len(input_data):
                if eof == 'stop':
                    return RunResult(''.join(output), step, 'eof', c)
                a = EOF_A
            else:
                a = ord(input_data[input_pos])
                input_pos += 1
        elif v == 39:   # rotr [d]; mov a, [d]
            a = mem[d] = rotate20(mem[d])
            if on_write is not None:
                on_write(step, c, d, a)
        elif v == 40:   # mov d, [d]
            d = mem[d]
        elif v == 62:   # crz [d], a; mov a, [d]
            a = mem[d] = crazy20(a, mem[d])
            if on_write is not None:
                on_write(step, c, d, a)
        elif v == 81:   # end
            return RunResult(''.join(output), step, 'end', c)
        # v == 68: nop

        if 33 <= mem[c] <= 126:
            mem[c] = ENCRYPT[mem[c] - 33]

        c = 0 if c == mem_size - 1 else c + 1
        d = 0 if d == mem_size - 1 else d + 1
        step += 1
