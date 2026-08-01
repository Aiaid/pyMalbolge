# I2 minimal counterexample: one level of recursion.
# Converting any single numbered flag in this program -- FLAG10 is the one
# the original bisection landed on -- is enough to break it under option one.
def f(n):
    if n < 1:
        return 65
    return f(n - 1)

putchar(f(1))
