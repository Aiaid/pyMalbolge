# Loops, break/continue and constant print(). Prints "ACE".
#
#   python3 -m malbolge compile examples/countdown.py --backend=direct -o countdown.mb
#   python3 -m malbolge --variant=malbolge20 countdown.mb

for i in range(6):
    if i % 2 == 1:
        continue
    if i > 4:
        break
    putchar(65 + i)
