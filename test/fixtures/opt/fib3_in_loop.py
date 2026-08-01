# Finding I7: the shipped chain miscompiles this, producing empty output.
#
# fib(3) on its own compiles and runs correctly (so does fib(6)), and a while
# loop on its own is fine. Calling the recursive function from inside the loop
# is what breaks. Expected output is '2'; the build halts on an illegal
# instruction having printed nothing.
def fib(n):
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)

i = 0
while i < 1:
    putchar(48 + fib(3))
    i = i + 1
