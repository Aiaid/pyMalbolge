g = 7

def change():
    global g
    g = 12
    return 3

def pair(a, b):
    return a + b

def touch():
    putchar(84)
    return 1

putchar(48 + (g + change()))
g = 7
putchar(48 + pair(g, change()))
g = 7
g += change()
putchar(48 + g)
if 0 and touch():
    pass
putchar(65)
if 1 or touch():
    pass
putchar(66)
if 2 < 1 < touch():
    pass
putchar(67)
x = 9
x = x > 5
putchar(48 + x)
limit = 3
for i in range(limit):
    putchar(65 + i)
    limit = 0
