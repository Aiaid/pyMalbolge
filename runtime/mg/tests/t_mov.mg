# MOV dst <- src (exact copy, src preserved). Clobbers TMP.
VAR SRC = 1162467007
VAR DST = 999999
VAR TMP = 0
DEF MAIN
  # --- SET_C1(TMP) ---
  ROT CON1
  OPR TMP
  ROT CON2
  OPR TMP
  ROT CON0
  OPR TMP
  # --- read SRC -> A ---
  ROT CON2
  OPR SRC
  ROT CON2
  OPR SRC
  # --- OPR TMP : TMP := r1(src) ---
  OPR TMP
  # --- SET_C1(DST) ---
  ROT CON1
  OPR DST
  ROT CON2
  OPR DST
  ROT CON0
  OPR DST
  # --- read TMP -> A ---
  ROT CON2
  OPR TMP
  ROT CON2
  OPR TMP
  # --- OPR DST : DST := r1(r1(src)) = src ---
  OPR DST
  # --- verify SRC preserved: output its low byte ---
  ROT CON2
  OPR SRC
  ROT CON2
  OPR SRC
  OUTPUT
  # --- DUMP DST at rotations 0,7,14 ---
  ROT CON2
  OPR DST
  ROT CON2
  OPR DST
  OUTPUT
  ROT DST
  ROT DST
  ROT DST
  ROT DST
  ROT DST
  ROT DST
  ROT DST
  OUTPUT
  ROT DST
  ROT DST
  ROT DST
  ROT DST
  ROT DST
  ROT DST
  ROT DST
  OUTPUT
END
