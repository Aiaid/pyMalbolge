a, b = 1, 2
a, b = b, a
g = 7

def change():
    global g
    g = 12
    putchar(84)
    return 3

def pair(a, b):
    return 10 * a + b

print(f"{a}:{b}", pair(b=g, a=change()), g, sep="|")
