"""On-demand decimal I/O routines shared by both Python frontends.

These run on the target VM, rather than on the compiling Python interpreter.
Input uses ASCII decimal digits, an optional leading +, and surrounding ASCII
whitespace. Invalid, empty, or overflowing input sets the private error flag;
the main-context caller reports the error and returns from the program.
"""

ERROR_NAME = "zzioerror"
INPUT_ERROR_MESSAGE = "error\n"
INTERNAL_NAMES = {"zzreadint", "zzprintint", ERROR_NAME}

PYTHON_HELPERS = {
    "ZZREADINT": """\
def zzreadint():
    global zzioerror
    zzioerror = 0
    value = 0
    has_digits = 0
    phase = 0
    c = getchar()
    while c != 10 and c != 59049:
        if c >= 48 and c <= 57:
            if phase == 2:
                zzioerror = 1
                return 0
            digit = c - 48
            if value > 348678440 or (value == 348678440 and digit > 0):
                zzioerror = 1
                return 0
            twice = value + value
            four_times = twice + twice
            value = four_times + four_times + twice + digit
            has_digits = 1
            phase = 1
        elif c == 32 or c == 9 or c == 11 or c == 12 or c == 13:
            if phase == 1:
                phase = 2
        elif c == 43 and phase == 0:
            phase = 1
        else:
            zzioerror = 1
            return 0
        c = getchar()
    if has_digits == 0:
        zzioerror = 1
    return value
""",
    "ZZPRINTINT": """\
def zzprintint(value):
    quotient = value // 10
    if quotient > 0:
        zzprintint(quotient)
    twice = quotient + quotient
    four_times = twice + twice
    putchar(48 + value - four_times - four_times - twice)
    return 0
""",
}

# Each entry contains one function definition. The C reader uses nested
# comparisons rather than native &&/||, whose temporary handling is unreliable
# in the upstream C frontend. Additions/subtractions are left-associated.
# zzprintint depends on the existing zzdiv helper.
C_HELPERS = {
    'zzreadint': """\
int zzreadint(){
  int value; int has_digits; int phase; int c; int digit;
  int twice; int four_times; int reading; int is_digit; int is_space;
  zzioerror = 0;
  value = 0; has_digits = 0; phase = 0;
  c = getchar();
  reading = 1;
  if(c == 10){ reading = 0; }
  if(c == 59049){ reading = 0; }
  while(reading != 0){
    is_digit = 0;
    if(c >= 48){ if(c <= 57){ is_digit = 1; } }
    if(is_digit != 0){
      if(phase == 2){ zzioerror = 1; return 0; }
      digit = c - 48;
      if(value > 348678440){ zzioerror = 1; return 0; }
      if(value == 348678440){
        if(digit > 0){ zzioerror = 1; return 0; }
      }
      twice = value + value;
      four_times = twice + twice;
      value = four_times + four_times + twice + digit;
      has_digits = 1; phase = 1;
    }else{
      is_space = 0;
      if(c == 32){ is_space = 1; }
      if(c == 9){ is_space = 1; }
      if(c == 11){ is_space = 1; }
      if(c == 12){ is_space = 1; }
      if(c == 13){ is_space = 1; }
      if(is_space != 0){
        if(phase == 1){ phase = 2; }
      }else{
        if(c == 43){
          if(phase == 0){ phase = 1; }
          else{ zzioerror = 1; return 0; }
        }else{ zzioerror = 1; return 0; }
      }
    }
    c = getchar();
    if(c == 10){ reading = 0; }
    if(c == 59049){ reading = 0; }
  }
  if(has_digits == 0){ zzioerror = 1; }
  return value;
}
""",
    'zzprintint': """\
int zzprintint(int value){
  int quotient; int twice; int four_times;
  quotient = zzdiv(value, 10);
  if(quotient > 0){ zzprintint(quotient); }
  twice = quotient + quotient;
  four_times = twice + twice;
  putchar(48 + value - four_times - four_times - twice);
  return 0;
}
""",
}
