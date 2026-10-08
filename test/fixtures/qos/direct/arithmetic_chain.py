def quotient(b):
    return 7 // b

def remainder(b):
    return 7 % b

def choose(mode, b):
    if mode == 68:
        return quotient(b)
    return remainder(b)

mode = getchar()
b = getchar() - 48
putchar(48 + choose(mode, b))
putchar(90)
