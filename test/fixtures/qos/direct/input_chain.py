def read():
    return int(input())

def outer():
    value = read()
    putchar(88)
    return value

putchar(48 + outer())
putchar(90)
