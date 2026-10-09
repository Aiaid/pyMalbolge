"""Euclid's algorithm with a guarded nonzero divisor."""

a = int(input())
b = int(input())
while b != 0:
    a, b = b, a % b
print(a)
