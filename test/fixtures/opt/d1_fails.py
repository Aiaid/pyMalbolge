# Finding I7, the cheap half of the non-monotonicity pair.
#
# d(1) = d(0) + d(0) = 32, so this should print a space. The shipped chain
# halts on an illegal instruction having printed nothing -- with no loop
# anywhere, which is what rules out "recursion inside a loop" as the
# characterization of I7.
#
# Compare d2_passes.py: one more constant, 9,306 more bytes, and it works.
def d(n):
    if n < 1:
        return 16
    return d(n - 1) + d(n - 1)

putchar(d(1))
