# Recursive Fibonacci. The inline double recursion below is the case the
# upstream C compiler miscompiles from fib(4) up; both backends here get it
# right, and the direct backend does so by construction.
#
#   python3 -m malbolge compile examples/fib.py --backend=direct -o fib.mb
#   python3 -m malbolge --variant=malbolge20 fib.mb    # prints 8


def fib(n):
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)


putchar(48 + fib(6))
