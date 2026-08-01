# I3 minimal counterexample: recursive fib plus a while loop.
# Recursion alone passes under option two, and a loop alone passes.
# Only the combination reaches the corrupted code cell.
def fib(n):
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)

i = 0
while i < 1:
    putchar(48 + fib(2))
    i = i + 1
