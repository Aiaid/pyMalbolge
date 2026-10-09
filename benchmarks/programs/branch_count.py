"""Count both outcomes of a branch in a runtime-sized loop."""

n = int(input())
low = 0
high = 0
for i in range(n):
    if i < 5:
        low += 1
    else:
        high += 1
print(low, high)
