"""Precomputed metadata for the hand-written original-Malbolge examples.

A front page that offers `hello.mal` as a card wants to say how big it is and
roughly how long it runs *before* the user clicks it. Size is a stat() call;
"how long it runs" is not derivable from the source at all -- Malbolge's own
self-modification decides it, so the only way to know is to run the program to
completion and count. That is far too slow to do in a browser at page load
(these are pure-Python millions-of-step runs), so it is done once, here, and
the answer is checked in as `examples/manifest.json`.

    build_manifest(paths, max_steps)   metadata for a list of .mal files
    describe(path, max_steps)          metadata for one
    load_image(source)                 the assembled image + cell count
    run_image(mem, input, max_steps)   an instrumented run to termination

    python -m test.diagnostics.examples_manifest -o examples/manifest.json

Two properties this file has to hold, because a stale or invented number here
is worse than no number:

**It never guesses.** A Malbolge program's step count has no upper bound the
loader can see, and nothing here extrapolates one. A run that hits
`--max-steps` is recorded as ``"steps": null, "truncated": true``, never as an
estimate; `step_limit` in the manifest header says what the cap was, so a
truncated entry still carries "more than this many steps". As it happens
every example currently in the repository terminates on its own, so no entry
is truncated today -- `quine.mal` is the expensive one at ~70M steps / ~20 s.

**It is reproducible.** Same files plus same `--max-steps` gives a
byte-identical manifest: no timestamps, no host paths, programs sorted by
name. `test/test_examples_manifest.py` regenerates the cheap entries and
diffs them against the checked-in file, which is what keeps it honest as the
examples change.

The run loop is a copy of `malbolge.malbolge.eval`'s, not a call to it, for
two reasons: `eval` reports neither a step count nor whether the program ever
executed an `in`, and `initialize` exits the process on a bad source character
instead of raising. The dispatch, the ENCRYPT rewrite and the pointer
wraparound are otherwise line-for-line the same, and the step counter matches
`MalbolgeDebugger.step_count`'s convention -- an instruction that terminates
the program (`end`, a read past the end of input, an illegal cell) is not
counted, because the debugger returns from those before its own increment.
"""

import argparse
import json
import os
import sys

from malbolge.malbolge import ENCRYPT, OPS_VALID, POW10, crazy, rotate

#: Default cap on executed instructions. Every example in the repository
#: terminates on its own well below this -- `quine.mal`, the longest at ~70M
#: steps, takes ~20 s -- so the cap is a guard against a future addition that
#: does not halt, not something the current manifest runs into. Raising it
#: never changes an existing entry; lowering it below ~70M turns `quine` into
#: a truncated one.
DEFAULT_MAX_STEPS = 100_000_000

#: Longest output string kept per program. The cards show a preview, and
#: `99bottles.mal` alone would otherwise be ~15 KB of the manifest.
OUTPUT_LIMIT = 200

#: Manifest format version, bumped when a field changes meaning.
SCHEMA = 1


def load_image(source):
    """Assemble `source` into a full 3**10-cell image.

    Mirrors `malbolge.malbolge.initialize`, except that a source problem
    raises `ValueError` instead of printing and calling `sys.exit`. Returns
    ``(mem, cells)`` where `cells` is how many cells the program itself
    occupies -- everything past that is the crazy-fill.
    """
    mem = [0] * POW10
    i = 0
    for ch in source:
        if ch == ' ' or ch == '\n':
            continue
        if i == POW10:
            raise ValueError('source is longer than the address space')
        if (ord(ch) + i) % 94 not in OPS_VALID:
            raise ValueError('invalid character %r at cell %d' % (ch, i))
        mem[i] = ord(ch)
        i += 1

    cells = i
    while i < POW10:
        mem[i] = crazy(mem[i - 1], mem[i - 2])
        i += 1
    return mem, cells


def run_image(mem, input_data='', max_steps=DEFAULT_MAX_STEPS):
    """Run an assembled image to termination, counting steps.

    `mem` is mutated (Malbolge programs rewrite themselves), so pass a fresh
    image per run. Returns a dict with:

        steps         instructions completed; `None` if `max_steps` was hit
        truncated     True when the run was cut short by `max_steps`
        stop_reason   'end' | 'illegal' | 'input_exhausted' | 'step_limit'
        reads_input   whether an `in` instruction ever executed
        input_consumed  characters actually taken from `input_data`
        output        everything written by `out`, untruncated

    `input_exhausted` is what an interactive program does here: the manifest
    runs every example with no input, and a program that reads stops at its
    first `in` rather than being fed something invented. `reads_input` is the
    field that says so; it is set even in that case, since the attempted read
    is exactly the evidence.
    """
    a = c = d = 0
    steps = 0
    reads = 0
    consumed = 0
    out = []

    while True:
        if mem[c] < 33 or mem[c] > 126:
            stop = 'illegal'
            break
        if steps >= max_steps:
            stop = 'step_limit'
            break

        v = (mem[c] + c) % 94

        if v == 4:                        # jmp [d]
            c = mem[d]
        elif v == 5:                      # out a
            out.append(chr(int(a % 256)))
        elif v == 23:                     # in a
            reads += 1
            if consumed >= len(input_data):
                stop = 'input_exhausted'
                break
            a = ord(input_data[consumed])
            consumed += 1
        elif v == 39:                     # rotr[d]; mov a, [d]
            a = mem[d] = rotate(mem[d])
        elif v == 40:                     # mov d, [d]
            d = mem[d]
        elif v == 62:                     # crz [d], a; mov a, [d]
            a = mem[d] = crazy(a, mem[d])
        elif v == 81:                     # end
            stop = 'end'
            break

        if 33 <= mem[c] <= 126:
            mem[c] = ENCRYPT[mem[c] - 33]

        c = 0 if c == POW10 - 1 else c + 1
        d = 0 if d == POW10 - 1 else d + 1
        steps += 1

    truncated = stop == 'step_limit'
    return {
        'steps': None if truncated else steps,
        'truncated': truncated,
        'stop_reason': stop,
        'reads_input': reads > 0,
        'input_consumed': consumed,
        'output': ''.join(out),
    }


def describe(path, max_steps=DEFAULT_MAX_STEPS):
    """Metadata for one .mal file, as it appears in the manifest.

    `output` is capped at OUTPUT_LIMIT characters (`output_len` keeps the true
    length); on a truncated run it is whatever the program had emitted before
    the cap, which the entry's own `truncated` flag is what marks as partial.
    """
    with open(path) as f:
        source = f.read()

    mem, cells = load_image(source)
    result = run_image(mem, max_steps=max_steps)
    output = result['output']

    return {
        'name': os.path.splitext(os.path.basename(path))[0],
        'file': os.path.basename(path),
        'bytes': os.path.getsize(path),
        'cells': cells,
        'steps': result['steps'],
        'truncated': result['truncated'],
        'stop_reason': result['stop_reason'],
        'reads_input': result['reads_input'],
        'output': output[:OUTPUT_LIMIT],
        'output_len': len(output),
        'output_truncated': len(output) > OUTPUT_LIMIT,
    }


def build_manifest(paths, max_steps=DEFAULT_MAX_STEPS):
    """Build the whole manifest dict. Programs come out sorted by name."""
    programs = sorted((describe(p, max_steps=max_steps) for p in paths),
                      key=lambda entry: entry['name'])
    return {
        'schema': SCHEMA,
        'variant': 'original',
        'step_limit': max_steps,
        'programs': programs,
    }


def dumps(manifest):
    """The manifest's canonical on-disk form -- pure ASCII, one program per
    block, trailing newline. Byte-stability is the point."""
    return json.dumps(manifest, indent=2, sort_keys=False) + '\n'


def main(argv=None):
    here = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('files', nargs='*',
                   help='.mal files (default: every one in examples/)')
    p.add_argument('-o', '--output', default=None,
                   help='write here instead of stdout')
    p.add_argument('--max-steps', type=int, default=DEFAULT_MAX_STEPS)
    args = p.parse_args(argv)

    files = args.files
    if not files:
        examples = os.path.join(here, 'examples')
        files = [os.path.join(examples, name)
                 for name in sorted(os.listdir(examples))
                 if name.endswith('.mal')]

    text = dumps(build_manifest(files, max_steps=args.max_steps))
    if args.output:
        with open(args.output, 'w') as f:
            f.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
