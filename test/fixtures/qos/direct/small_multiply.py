x = 1
putchar(48 + x * 0)
putchar(48 + x * 1)
putchar(48 + x * 2)
putchar(48 + x * 3)
putchar(48 + x * 7)
putchar(48 + x * 8)
putchar(48 + x * 16)

def value():
    putchar(84)
    return 7

putchar(48 + value() * 0)
putchar(48 + value() * 3)
x = 7
x *= 3
putchar(48 + x)
x = 3486784400
putchar(65 + (x * 2 == 3486784399))
