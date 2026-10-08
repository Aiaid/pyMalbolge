zero = 0
five = 5
seven = 7
putchar(48 + (five or seven))
putchar(48 + (zero and seven))
putchar(48 + (zero or seven))
putchar(48 + (five and seven))
g = 2

def bump():
    global g
    g = 7
    putchar(84)
    return 3

if 1 < g < bump():
    putchar(65)
if 3 < 2 < bump():
    putchar(88)
putchar(66)
