# Compile with:
#   python3 -m malbolge compile examples/hello.py -o hello.mb
#   python3 -m malbolge --variant=malbolge20 hello.mb
#
# print() takes compile-time-constant arguments only; it is lowered to a
# chain of putchar calls.
print("Hello, world!")
