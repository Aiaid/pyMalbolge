# CLAUDE.md

@AGENTS.md

Claude Code-specific shell guidance follows. Shared project rules are in
`AGENTS.md`.

### Searching the repo

**`grep` in a Claude Code shell is a function wrapping `ugrep`, and the
wrapper passes `--ignore-files`** — so searches honour `.gitignore`. That is
the wrapper's doing, not ugrep's default; plain `ugrep` ignores `.gitignore`
unless told otherwise. Check with `type grep` if a search behaves unexpectedly.

**`command grep` is a different program**, not the same search with the
wrapper peeled off: it bypasses the function and reaches `/usr/bin/grep` —
BSD grep, not ugrep — which honours no ignore rules and takes different
flags. So it cannot be used to check what the wrapper does; a parallel
session spent three rounds of increasingly careful experiments concluding
the wrapper had no effect, every round carrying `command` along as the
unexamined constant.

`docs/research/` is gitignored (it lives in a private companion repository),
so a plain `grep -r` over this repo silently skips every research note and
returns a *false negative* — the hits are there, you just cannot see them.

```bash
grep -rn "some_symbol" .                       # skips docs/research/ silently
grep -rn "some_symbol" . docs/research/        # name the path explicitly (simplest)
grep -rn --no-ignore-files \
     --exclude-dir={.venv,ref,pyenv,dist} \
     "some_symbol" .                           # or search everything
```

The flag is `--no-ignore-files`. **`--no-ignore` is ripgrep's spelling and
ugrep rejects it** — stdout empty, exit 2, the complaint on stderr only, so
with `2>/dev/null` in the pipe it is indistinguishable from "no matches". The
`--exclude-dir` part is not optional either: without it the search descends
into `.venv/` and `ref/`.

Check the exit code, not just the line count: 1 means "no matches", 2 means
the search never ran.

This matters most when checking "is this symbol/claim still referenced
anywhere?" before deleting or rewriting something. Three sessions have now
been misled by it — the third being an earlier revision of this very
paragraph, which recommended `--no-ignore` and was itself verified with
`2>&1 | wc -l`, counting ugrep's error message as if it were search results.
