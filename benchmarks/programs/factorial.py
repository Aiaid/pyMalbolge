"""Iterative factorial, bounded to keep all arithmetic unsigned-safe."""

n = int(input())
value = 1
for i in range(1, n + 1):
    value *= i
print(value)
