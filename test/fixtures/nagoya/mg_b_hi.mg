# Prints "Hi" using VAR + ROT + OUTPUT (values are 3*ASCII, same
# encoding trick as ref/nagoya-ternary/sample/hello.mg).
VAR H = 216   # 3*'H' (72)
VAR I = 315   # 3*'i' (105)
DEF MAIN
  ROT H
  OUTPUT
  ROT I
  OUTPUT
END
