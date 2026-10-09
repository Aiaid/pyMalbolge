"""Test alternating calls and stack depth using mutually recursive parity."""

def iseven(n):
    if n == 0:
        return 1
    return isodd(n - 1)


def isodd(n):
    if n == 0:
        return 0
    return iseven(n - 1)


n = int(input())
print(iseven(n))
