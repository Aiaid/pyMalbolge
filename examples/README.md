# Examples

## Python sources for the compiler

Compile these to Malbolge20 with `python3 -m malbolge compile <file> -o out.mb`,
then run with `python3 -m malbolge --variant=malbolge20 out.mb`.

| File | Demonstrates | Output |
|---|---|---|
| `hello.py` | `print()` with a constant argument | `Hello, world!` |
| `fib.py` | recursion, including inline double recursion | `8` |
| `countdown.py` | `for` / `range`, `break`, `continue`, `%` | `ACE` |

Expect multi-MB `.mb` files and runtimes of seconds to a minute — see the
performance section of the top-level README.

## Hand-written Malbolge programs (original variant)

Run with `python3 -m malbolge <file>`.

- `hello.mal` : from https://en.wikipedia.org/wiki/Malbolge#Example_Program
- `cat.mal` : from https://esolangs.org/wiki/malbolge#Cat
- `quine.mal` : from http://matthias-ernst.eu/malbolgequine.html
- `99bottles.mal` : from http://www.99-bottles-of-beer.net/language-malbolge-995.html
- `truth.mal` : from https://esolangs.org/wiki/Truth-machine#Malbolge
- `cat2.mal` : from https://commons.wikimedia.org/wiki/File:Malbolge_cat_program.png
