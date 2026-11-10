"""A bounded loop controlled by one ASCII digit."""

n = getchar() - 48
i = 0
while i < n:
    putchar(65 + i)
    i += 1
