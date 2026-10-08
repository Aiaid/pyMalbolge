# Double-recursive Fibonacci with ordinary Python decimal input/output.
# Malbolge20's word range permits n=0..47; exponential runtime makes small
# inputs such as 6, 7 and 10 more suitable for demonstrations.


def fib(n):
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)


n = int(input())
if 0 <= n <= 47:
    print(fib(n))
else:
    print("error")
