"""A lazy boolean expression must preserve input consumption."""

first = getchar()
if first == 0 or getchar() == 66:
    putchar(65)
else:
    putchar(67)
