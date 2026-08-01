# Finding I7, the other half of the pair. d(2) = 64, prints '@', and works --
# while doing strictly more work through the same machinery than d1_fails.py.
#
# The two differ by one constant, which shifts the whole layout up by 9,306
# cells while preserving mod-94 and mod-3 alignment. The same shift breaks
# fib(2)-in-a-loop, in the opposite direction. Correctness here moves with
# where things land, not with what the program says.
def d(n):
    if n < 1:
        return 16
    return d(n - 1) + d(n - 1)

putchar(d(2))
