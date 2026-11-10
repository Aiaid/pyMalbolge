"""Double recursion without the large decimal input/output helpers."""

def fib(n):
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)

putchar(fib(getchar() - 48))
