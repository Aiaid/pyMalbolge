"""
malbolge.compiler.mc2mb -- pure-Python port of the Nagoya University "lowass"
assembler (Low-Level-Assembly / .mc -> Malbolge20 / .mb).

This is a faithful port of the two-stage MIT-licensed toolchain in
``ref/nagoya-lowass``:

* **Stage 1** -- ``parse_mc2.pl``: parses the LAL (.mc) source into a
  Malbolge20 memory image (the textual ``.data`` file).  ``_parse_mc_to_data``
  reproduces the ``.data`` output **byte-for-byte** (CRLF line endings
  included).  The Perl ``.data`` output is entirely array-index ordered -- the
  only hash iteration that touches it (locating the ``BASE`` label) is
  order-insensitive -- so the result is independent of ``PERL_HASH_SEED`` and
  can be reproduced exactly.

* **Stage 2** -- ``init/{init,dmod,comm}.cpp``: reads the ``.data`` memory image
  and emits the self-bootstrapping Malbolge20 program (.mb).  ``_data_to_mb``
  ports the data-module setup, the ``op_decode`` bootstrap code generator, and
  the direct/indirect code layout.

  **Deliberate divergence from upstream:** the C++ ``init`` fills every unused
  padding cell with a ``srand(time(NULL))``-seeded random legal NOP opcode
  (``init.cpp`` "unset region" loop), so its ``.mb`` is not byte-reproducible.
  This port fills padding **deterministically** instead (a fixed rotation
  through the eight legal NOP opcodes, seeded only by cell position).  The
  program region and data-unit cells are unaffected, so behaviour is identical;
  only the don't-care padding differs.  Conformance is therefore verified by
  I/O behaviour (running both .mb variants on both interpreters) plus a
  structural diff of the non-padding cells.

Public API::

    assemble_mc_to_mb(mc_source: str) -> str      # .mc text -> .mb text
    Mc2MbError                                     # raised on any error

Reference: https://git.trs.css.i.nagoya-u.ac.jp/malbolge  (Nagoya Univ., MIT)
"""

from __future__ import annotations

__all__ = ["assemble_mc_to_mb", "parse_mc_to_data", "data_to_mb", "Mc2MbError"]


class Mc2MbError(Exception):
    """Raised on any parse, semantic, or code-generation error."""


# ---------------------------------------------------------------------------
# Shared translation tables (from init.h / parse_mc2.pl)
# ---------------------------------------------------------------------------

_XLAT1 = ("+b(29e*j1VMEKLyC})8&m#~W>qxdRp0wkrUo[D7,XTcA\"lI"
          ".v%{gJh4G\\-=O@5`_3i<?Z';FNQuY]szf$!BS/|t:Pn6^Ha")

_REV_XLAT1 = ("rM6qR4f#2'!HZPu?)$aW^{G3%xgc[9d]Ls0F,hX}OU-.+i\\"
              "yj=tJC*8IleEYm|`_~\"K<&pTVb(AN5zD>:BnwkQ@;/oSv17")

assert len(_XLAT1) == 94 and len(_REV_XLAT1) == 94

_XLAT1_B = [ord(c) for c in _XLAT1]
_REV_XLAT1_B = [ord(c) for c in _REV_XLAT1]

# nop_loop table from parse_mc2.pl (@nop_loop): the S_NOP opcode byte to place
# at indirect-unit position (j % 94).
_NOP_LOOP = ("FFFFFFFrFFFrFFFFFFFFFFFFrrFFffFFFFFFFFFFFFFrFFFr"
             "FFFFFFFFFFFrrFFrrFFFFFFFFFFFFFFFFFrFFFfFfFFFgF")
assert len(_NOP_LOOP) == 94
_NOP_LOOP_B = [ord(c) for c in _NOP_LOOP]


def _xlat1(c, C):
    """init.h Xlat1(c,C) = xlat1[(c - 33 + C) % 94]  (returns byte value)."""
    return _XLAT1_B[(c - 33 + C) % 94]


def _rev_xlat1_perl(c, C):
    """parse_mc2.pl RevXlat1: (rev_xlat1[c-33] - 33 - C) % 94 + 33.

    Perl's ``%`` yields a non-negative result for a positive modulus, matching
    Python's ``%``.
    """
    return (_REV_XLAT1_B[c - 33] - 33 - C) % 94 + 33


def _rev_xlat1_c(c, C):
    """init.h RevXlat1(c,C) = ((rev_xlat1[c-33] - 33 - (C%94) + 94*2) % 94) + 33."""
    return ((_REV_XLAT1_B[c - 33] - 33 - (C % 94) + 94 * 2) % 94) + 33


# ---------------------------------------------------------------------------
# Stage 1: parse_mc2.pl -> .data
# ---------------------------------------------------------------------------

import re

# Instruction -> single-char opcode used by PutInst (parse_mc2.pl output stage).
_INST_CHAR = {
    "DUP": "o", "OPR": "p", "ROT": "*", "JMP": "i",
    "MOV_D": "j", "HALT": "v", "OUTPUT": "<", "INPUT": "/",
}


def _perl_num(v):
    """Mimic Perl's numeric coercion of a scalar (leading numeric prefix,
    else 0).  Used to reproduce Perl's ``$x == undef`` / numeric-context
    truthiness exactly."""
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return v
    m = re.match(r'\s*([+-]?\d+)', str(v))
    return int(m.group(1)) if m else 0


def _maxidx(d):
    """Highest key of a sparse dict, or -1 if empty (Perl's $#array)."""
    return max(d) if d else -1


def _put_inst(char, pos):
    """PutInst(char, pos) = RevXlat1(ord(char), pos)  (parse_mc2.pl)."""
    return _rev_xlat1_perl(ord(char), pos)


def _put_inst_value(inst, j):
    """Convert a resolved unit instruction cell to its output byte value."""
    if inst in _INST_CHAR:
        return _put_inst(_INST_CHAR[inst], j)
    m = re.match(r'^(\d+)$', str(inst))
    if m:
        return int(m.group(1))
    raise Mc2MbError('UNIT name is not correct "%s"' % inst)


def parse_mc_to_data(mc_source: str) -> str:
    """Port of parse_mc2.pl: LAL (.mc) text -> Malbolge20 ``.data`` text.

    The returned string is byte-identical to ``PERL_HASH_SEED=0 perl
    parse_mc2.pl`` output (CRLF line endings).
    """
    # ---- fixed tables from parse_mc2.pl --------------------------------
    flag_cicle_addr = [
        [64, 60],
        [92, 0, 9, 29],
        [32, 0, 74, 83, 0],
        [3, 31, 17, 0, 0, 0],
        [84, 0, 68, 72, 58, 0, 0, 0, 61],
    ]
    flag_cicle_value = [
        [70, 74],
        [42, 114, 125, 105],
        [102, 96, 60, 51, 41],
        [37, 103, 117, 111, 120, 58],
        [50, 80, 66, 62, 76, 79, 67, 85, 73],
    ]
    flag_count = [0, 0, 0, 0, 0]
    jflag_cicle_addr = [[24, 28]]
    flag_map = {2: 0, 4: 1, 5: 2, 6: 3, 9: 4}

    stdUT_name = ["END", "OUTPUT", "SKIP", "INPUT", "ROT", "JMP", "OPR"]
    stdUT_check = {n: 0 for n in stdUT_name}
    # stdUT[i] = sparse unit dict.
    stdUT = [
        {0: "DUP", 1: "HALT"},                    # END
        {24: "DUP", 25: "OUTPUT", 26: "JMP"},     # OUTPUT
        {39: "DUP", 40: "JMP"},                   # SKIP
        {46: "DUP", 47: "INPUT", 48: "JMP"},      # INPUT
        {58: "DUP", 59: "ROT", 60: "JMP"},        # ROT
        {63: "DUP", 64: "MOV_D", 65: "JMP"},      # JMP
        {85: "DUP", 86: "OPR", 87: "JMP"},        # OPR
    ]
    stdUT_label_sec = {"END": 1, "OUTPUT": 25, "SKIP": 40,
                       "INPUT": 47, "ROT": 59, "JMP": 64, "OPR": 86}

    InsGeneNum = 850
    DataModGeneNum = 865
    data_dup = -1

    # ---- parser state --------------------------------------------------
    UT = []            # list of sparse dict {addr: value}
    UT_check = {}      # {ut_index: 1 or -1}
    UT_label = {}      # {label: [ut_index, addr]}
    UT_upper_addr = {}

    RT = []            # list of sparse dict {addr: value}
    RT_label = []      # list of dict {label: addr}
    RT_label_check = []  # list of dict {label: 1}
    RT_name = {}       # {name: rt_index}
    RT_offset = []     # list, per routine

    startLABEL = [None, None]  # [routine, entry-label]

    def ut(i):
        while len(UT) <= i:
            UT.append({})
        return UT[i]

    def rt(i):
        while len(RT) <= i:
            RT.append({})
            RT_label.append({})
            RT_label_check.append({})
            RT_offset.append(0)
        return RT[i]

    UT_count = 0
    RT_count = 0
    RT_addr = 0
    UT_upper_count = 0
    UT_lower_check = -1
    UT_label_tmp = []

    mode = 0
    TXT_line = 0

    src_lines = mc_source.split("\n")
    idx = 0
    redo_line = None  # holds a line to reprocess (Perl `redo`)

    def strip_line(s):
        s = re.sub(r'#.*', '', s)
        s = re.sub(r'//.*', '', s)
        s = re.sub(r'^\s+', '', s)
        s = re.sub(r'\s+$', '', s)
        return s

    while idx < len(src_lines) or redo_line is not None:
        if redo_line is not None:
            line = redo_line
            redo_line = None
            # Perl: `$TXT_line--; redo` then body re-does `$TXT_line++`; net 0.
        else:
            line = strip_line(src_lines[idx])
            idx += 1
            TXT_line += 1
            if line == "":
                continue

        if mode == 0:
            m = re.match(r'^PROGRAM_START_TO\s*([A-Za-z]\w*)@([A-Za-z]\w*)', line)
            if m:
                startLABEL[0] = m.group(2)
                startLABEL[1] = m.group(1)
                mode += 1
            else:
                raise Mc2MbError('line_%d :syntax_error "%s"' % (TXT_line, line))

        elif mode == 1:
            m = (re.match(r'^FLAG\s+\s*(\d+)\s*/\s*(\d+)\s*,\s*([A-Za-z]\w*)', line)
                 or re.match(r'^FLAG\s+\s*(\d+)\s*/\s*(\d+)\s+\s*([A-Za-z]\w*)', line)
                 or re.match(r'^FLAG\s+\s*\[\s*(\d+)\s*/\s*(\d+)\s*\]\s+\s*([A-Za-z]\w*)', line))
            mj = re.match(r'^JFLAG\s*,\s*([A-Za-z]\w*)', line) or \
                re.match(r'^JFLAG\s+\s*([A-Za-z]\w*)', line)
            if m:
                num = int(m.group(1))
                denom = int(m.group(2))
                label = m.group(3)
                # Perl: ($2==2||4||5||6||9) && $1<$2 && (S1>=0 always true)
                if denom in (2, 4, 5, 6, 9) and num < denom:
                    a = flag_map[denom]
                    b = flag_count[a]
                    c = len(flag_cicle_addr[a])
                    base = flag_cicle_addr[a][b]
                    u = ut(UT_count)
                    u[base - 1] = "DUP"
                    if num == 0:
                        u[base] = "MOV_D"
                    else:
                        u[base] = flag_cicle_value[a][(b + num) % denom]
                    u[base + 1] = "JMP"
                    UT_label[label] = [UT_count, base]
                    UT_check[UT_count] = 1 if num == 0 else -1
                    # advance flag_count (do/while: skip addr==0 slots)
                    while True:
                        flag_count[a] = (flag_count[a] + 1) % c
                        if flag_cicle_addr[a][flag_count[a]] != 0:
                            break
                    UT_upper_addr[UT_count] = -1
                    UT_count += 1
                else:
                    pass  # silently dropped, matching Perl
            elif mj:
                label = mj.group(1)
                a = 0
                b = flag_count[a]
                c = len(flag_cicle_addr[a])
                base = jflag_cicle_addr[a][b]
                u = ut(UT_count)
                u[base - 1] = "DUP"
                u[base] = "JMP"
                u[base + 1] = "JMP"
                UT_label[label] = [UT_count, base]
                UT_check[UT_count] = 1
                while True:
                    flag_count[a] = (flag_count[a] + 1) % c
                    if jflag_cicle_addr[a][flag_count[a]] != 0:
                        break
                UT_upper_addr[UT_count] = -1
                UT_count += 1
            elif re.match(r'^UNIT\s*{', line):
                mode = 2
                UT_check[UT_count] = 1
                UT_upper_count = 0
                UT_lower_check = -1
            elif re.match(r'^UNIT\s*(<.+>)?\s*{', line):
                raise Mc2MbError('line_%d"%s"\nI\'m sorry. Don\'t write option.'
                                 % (TXT_line, line))
            elif (re.match(r'^ROUTINE\s*\(\s*([A-Za-z]\w*)\s*\)\s*{', line) or
                  re.match(r'^ROUTINE\s+\s*([A-Za-z]\w*)\s*{', line)):
                mr = (re.match(r'^ROUTINE\s*\(\s*([A-Za-z]\w*)\s*\)\s*{', line) or
                      re.match(r'^ROUTINE\s+\s*([A-Za-z]\w*)\s*{', line))
                rt(RT_count)
                RT_offset[RT_count] = 0
                RT_name[mr.group(1)] = RT_count
                mode = 3
            else:
                raise Mc2MbError('line_%d :syntax_error "%s"' % (TXT_line, line))

        elif mode == 2:
            m_lab = re.match(r'^([A-Za-z]\w*)\s*:\s*(.*)$', line)
            m_addr = re.match(r'^(\d+)\s*:\s*(.*)', line)
            if m_lab:
                s2 = m_lab.group(2)
                UT_label_tmp.append(m_lab.group(1))
                if re.match(r'^(END|OUTPUT|SKIP|INPUT|ROT|JMP|OPR)$', m_lab.group(1)):
                    stdUT_check[m_lab.group(1)] = 2
                if s2 != "":
                    redo_line = strip_line(s2)
                    continue
            elif m_addr:
                addr = int(m_addr.group(1))
                s2 = m_addr.group(2)
                if UT_lower_check >= addr:
                    UT_upper_count += 1
                    UT_lower_check = -1
                else:
                    UT_lower_check = addr
                tmp = UT_upper_count * 94 + addr
                u = ut(UT_count)
                mi = re.match(r'^(DUP|OPR|ROT|JMP|MOV_D|HALT|OUTPUT|INPUT)$', s2)
                mn = re.match(r'^(NOOP)$', s2)
                mnum = re.match(r'^(\d+)', s2)
                if mi:
                    u[tmp] = mi.group(1)
                elif mn:
                    u[tmp] = mn.group(1)
                    UT_check[UT_count] = -1
                elif mnum:
                    u[tmp] = mnum.group(1)
                    UT_check[UT_count] = -1
                else:
                    raise Mc2MbError('EXECUTION name is not correct "%s"' % s2)
                for lbl in UT_label_tmp:
                    UT_label[lbl] = [UT_count, tmp]
                UT_label_tmp = []
            elif re.match(r'^}', line):
                mode = 1
                UT_count += 1
            # else: silently ignored (matches Perl: no else branch)

        elif mode == 3:
            m_align = re.match(r'^ALIGN\s+([012])', line)
            m_lab = re.match(r'^([A-Za-z]\w*)\s*:\s*(.*)$', line)
            if m_align:
                RT_addr += (3 + int(m_align.group(1)) - RT_addr % 3) % 3
                rt(RT_count)[RT_addr] = line
                RT_addr += 1
            elif m_lab:
                lab = m_lab.group(1)
                s2 = m_lab.group(2)
                if lab not in RT_label_check[RT_count]:
                    RT_label[RT_count][lab] = RT_addr
                    RT_label_check[RT_count][lab] = 1
                else:
                    raise Mc2MbError('line_%d :label_error "%s"' % (TXT_line, lab))
                if s2 != "":
                    redo_line = strip_line(s2)
                    continue
            elif re.match(r'^(JMP)(\s+.*)?', line):
                if stdUT_check["JMP"] == 0:
                    stdUT_check["JMP"] = 1
                rt(RT_count)[RT_addr] = "JMP"
                RT_addr += 1
                RT[RT_count][RT_addr] = line
                RT_addr += 1
            elif re.match(r'^(END|OUTPUT|SKIP|INPUT|ROT|OPR)(\s+.*)?', line):
                nm = re.match(r'^(END|OUTPUT|SKIP|INPUT|ROT|OPR)(\s+.*)?', line).group(1)
                if stdUT_check[nm] == 0:
                    stdUT_check[nm] = 1
                rt(RT_count)[RT_addr] = line
                RT_addr += 1
            elif re.match(r'^(DUP)', line):
                rt(RT_count)[RT_addr] = line
                RT_addr += 1
            elif re.match(r'^}', line):
                RT_count += 1
                mode = 4
            else:
                rt(RT_count)[RT_addr] = line
                RT_addr += 1

        elif mode == 4:
            mr = (re.match(r'^ROUTINE\s*\(\s*([A-Za-z]\w*)\s*\)\s*{', line) or
                  re.match(r'^ROUTINE\s+\s*([A-Za-z]\w*)\s*{', line))
            if mr:
                rt(RT_count)
                RT_offset[RT_count] = 0
                if mr.group(1) in RT_name:
                    raise Mc2MbError('line_%d :routine_name_error "%s"'
                                     % (TXT_line, line))
                RT_name[mr.group(1)] = RT_count
                mode = 3
                RT_addr = 0
            else:
                raise Mc2MbError('line_%d :syntax_error "%s"' % (TXT_line, line))

    # ---- append used standard units -----------------------------------
    for i, nm in enumerate(stdUT_name):
        if stdUT_check[nm] == 1:
            while len(UT) <= UT_count:
                UT.append({})
            UT[UT_count] = dict(stdUT[i])
            UT_check[UT_count] = 1
            UT_label[nm] = [UT_count, stdUT_label_sec[nm]]
            UT_count += 1

    # ---- entry label defined? -----------------------------------------
    a = RT_name.get(startLABEL[0])
    if a is None or startLABEL[1] not in RT_label[a]:
        raise Mc2MbError('ENTRY LABEL[%s@%s] is not include:syntax_error.'
                         % (startLABEL[1], startLABEL[0]))

    # ---- pass 2: validate + insert NOOPs into units -------------------
    for count in range(len(RT)):
        rtc = RT[count]
        for addr in range(_maxidx(rtc) + 1):
            data = rtc.get(addr)
            if data is None:
                continue
            data = str(data)
            m = re.match(r'^(IF|REV|NEXT)\s+(.+)$', data)
            if m:
                if m.group(2) not in UT_label:
                    raise Mc2MbError('unit label undefined "%s"' % data)
                continue
            m = re.match(r'^(BRANCH|JMP)\s+(.+)$', data)
            if m:
                data1 = m.group(2)
                m2 = re.match(r'^([A-Za-z]\w*)@([A-Za-z]\w*)$', data1)
                if m2:
                    if RT_name.get(m2.group(2), -1) < 0:
                        raise Mc2MbError('routine_name undefined "%s"' % data)
                    elif m2.group(1) not in RT_label_check[RT_name[m2.group(2)]]:
                        raise Mc2MbError('%s\'s label undefined111 "%s"'
                                         % (m2.group(1), data))
                    continue
                m3 = re.match(r'^([A-Za-z]\w*)\s*-([0-9]+)$', data1)
                if m3:
                    if m3.group(1) not in RT_label_check[count]:
                        raise Mc2MbError('data label undefined "%s"' % data)
                    continue
                if data1 not in RT_label_check[count]:
                    raise Mc2MbError('data label undefined "%s"' % data)
                continue
            if re.match(r'^(JMP)', data):
                continue
            m = re.match(r'^([A-Za-z]\w*)@([A-Za-z]\w*)$', data)
            if m:
                if m.group(2) not in RT_name:
                    raise Mc2MbError('routine_name undefined "%s"' % data)
                elif m.group(1) not in RT_label_check[RT_name[m.group(2)]]:
                    raise Mc2MbError('label undefined "%s"' % data)
                continue
            if re.match(r'^(DUP)$', data):
                continue
            m = re.match(r'^([A-Za-z]\w*)(\s+(.+))?$', data)
            if m:
                g1 = m.group(1)
                g3 = m.group(3)
                if g1 in UT_label:
                    if g3 is not None:
                        if g3 in RT_label_check[count]:
                            target = RT_label[count][g3]
                            if target == addr + 1:
                                pass
                            elif target > addr + 1:
                                length = target - (addr + 1)
                                ua = UT_label[g1][0]
                                ub = UT_label[g1][1]
                                if length >= ub:
                                    raise Mc2MbError('unit label noop error "%s"' % data)
                                ud = ut(ua)
                                for i2 in range(length):
                                    ud[ub - i2 - 1] = "NOOP"
                                d = ud.get(ub - length - 1)
                                if re.search(r'~(NOOP|DUP)$', str(d) if d is not None else "") \
                                        or _perl_num(d) == 0:
                                    ud[ub - length - 1] = "NOOP"
                                else:
                                    raise Mc2MbError('unit label noop error "%s"' % data)
                                UT_check[ua] = -1
                            else:
                                raise Mc2MbError('data label point error "%s"' % data)
                        else:
                            raise Mc2MbError('data label undefined "%s"' % data)
                elif g1 in RT_label_check[count]:
                    pass
                else:
                    raise Mc2MbError('label undefined "%s"' % data)
            # else: numbers etc, nothing

    # ---- pack UT into UT_dir / UT_indir -------------------------------
    UT_dir = []
    UT_indir = []
    relateUT = {}
    count_dir = -1
    count_indir = -1

    for count in range(len(UT)):
        if UT_check.get(count) == 1:
            placed = False
            for i in range(len(UT_dir)):
                if set(UT_dir[i].keys()) & set(UT[count].keys()):
                    continue
                relateUT[count] = (1, i)
                for k, v in UT[count].items():
                    UT_dir[i][k] = v
                placed = True
                break
            if not placed:
                count_dir += 1
                relateUT[count] = (1, count_dir)
                UT_dir.append(dict(UT[count]))
        elif UT_check.get(count) == -1:
            placed = False
            for i in range(len(UT_indir)):
                if set(UT_indir[i].keys()) & set(UT[count].keys()):
                    continue
                relateUT[count] = (-1, i)
                for k, v in UT[count].items():
                    UT_indir[i][k] = v
                placed = True
                break
            if not placed:
                count_indir += 1
                relateUT[count] = (-1, count_indir)
                UT_indir.append(dict(UT[count]))

    # ---- offsets ------------------------------------------------------
    insNum_indir = 0
    for i in range(len(RT)):
        insNum_indir += _maxidx(RT[i]) + 1
    insNum_indir += (count_indir + 1) * 94

    tmp = DataModGeneNum + (3 + insNum_indir) * InsGeneNum
    UT_dir_firstOffset = (tmp - tmp % 94) + 94
    RT_firstOffset = UT_dir_firstOffset + (count_dir + 1) * 94 + 94
    if RT_firstOffset % 3 == 0:
        RT_firstOffset += 0
    elif RT_firstOffset % 3 == 1:
        RT_firstOffset += 2
    else:
        RT_firstOffset += 1

    # ---- determine routine offsets ------------------------------------
    memory = {}
    offset = RT_firstOffset
    for i in range(len(RT_offset)):
        if RT_offset[i] != 0:
            if RT_offset[i] + _maxidx(RT[i]) < offset:
                offset = RT_offset[i] + _maxidx(RT[i]) + 1
            for j in range(RT_offset[i], RT_offset[i] + _maxidx(RT[i]) + 1):
                if memory.get(j) is None:
                    memory[j] = 1
                else:
                    raise Mc2MbError('data overlapping')
    i = 0
    while i < len(RT_offset):
        if RT_offset[i] == 0:
            memory_check = 0
            for j in range(offset, offset + _maxidx(RT[i]) + 1):
                if memory.get(j) == 1:
                    memory_check = j
            if memory_check == 0:
                RT_offset[i] = offset
                offset += _maxidx(RT[i]) + 2
            else:
                offset = memory_check
                while memory.get(offset) == 1:
                    offset += 1
                continue  # Perl `redo` (re-process same i)
        i += 1

    UT_indir_firstOffset = (offset - offset % 94) + 94

    # ---- pass 3: resolve RT cells to numeric addresses ----------------
    for count in range(len(RT)):
        rtc = RT[count]
        for addr in range(_maxidx(rtc) + 1):
            if addr not in rtc:
                continue
            data = str(rtc[addr])
            if re.match(r'^[0-2]{20}t$', data):
                t = 0
                k = 19683 * 59049
                for pos in range(20):
                    t += int(data[pos]) * k
                    k //= 3
                rtc[addr] = t
            elif re.match(r'^(\d+)$', data):
                if int(data) > 3486784400:
                    raise Mc2MbError('num is over 3486784400 "%s"' % data)
                # leave as-is
            else:
                m = re.match(r'^([A-Za-z]\w*)(\s+(.+))?$', data)
                if not m:
                    raise Mc2MbError('cannot execution %s' % data)
                g1 = m.group(1)
                g3 = m.group(3)
                if (g1 == "REV" or g1 == "NEXT") and g3 in UT_label:
                    ua, ub = UT_label[g3]
                    c, d = relateUT[ua]
                    if c == 1:
                        rtc[addr] = UT_dir_firstOffset + d * 94 + ub
                    elif c == -1:
                        rtc[addr] = UT_indir_firstOffset + d * 94 + ub
                elif g1 == "DUP":
                    rtc[addr] = 0
                elif g1 == "IF" and g3 in UT_label:
                    ua, ub = UT_label[g3]
                    c, d = relateUT[ua]
                    if c == 1:
                        rtc[addr] = UT_dir_firstOffset + d * 94 + ub - 1
                    elif c == -1:
                        rtc[addr] = UT_indir_firstOffset + d * 94 + ub - 1
                elif g1 == "BRANCH":
                    aa = bb = None
                    if g3 in RT_label[count]:
                        aa = count
                        bb = RT_label[count][g3]
                    else:
                        m2 = re.match(r'^([A-Za-z]\w*)@([A-Za-z]\w*)$', g3)
                        if m2:
                            aa = RT_name[m2.group(2)]
                            bb = RT_label[aa][m2.group(1)]
                    rtc[addr] = RT_offset[aa] + bb - 1
                elif re.match(r'^(JMP)\s+(.+)$', data):
                    g2 = re.match(r'^(JMP)\s+(.+)$', data).group(2)
                    aa = bb = None
                    msub = re.match(r'^([A-Za-z]\w*)\s*-([0-9]+)$', g2)
                    if msub:
                        if msub.group(1) in RT_label[count]:
                            aa = count
                            bb = RT_label[count][msub.group(1)]
                            rtc[addr] = RT_offset[aa] + bb - int(msub.group(2)) - 1
                            continue
                    elif g2 in RT_label[count]:
                        aa = count
                        bb = RT_label[count][g2]
                    else:
                        m2 = re.match(r'^([A-Za-z]\w*)@([A-Za-z]\w*)$', g2)
                        if m2:
                            aa = RT_name[m2.group(2)]
                            bb = RT_label[aa][m2.group(1)]
                    rtc[addr] = RT_offset[aa] + bb - 1
                elif g1 in UT_label:
                    a1, a2 = UT_label[g1]
                    b1, b2 = relateUT[a1]
                    if g3 in RT_label[count]:
                        c1, c2 = count, RT_label[count][g3]
                        dd = RT_offset[c1] + c2
                        ee = RT_offset[count] + addr
                        length = dd - ee
                    else:
                        length = 1
                    if b1 == 1:
                        rtc[addr] = UT_dir_firstOffset + b2 * 94 + a2 - length
                    elif b1 == -1:
                        rtc[addr] = UT_indir_firstOffset + b2 * 94 + a2 - length
                elif re.match(r'^([A-Za-z]\w*)\s*-([0-9]+)$', data):
                    msub = re.match(r'^([A-Za-z]\w*)\s*-([0-9]+)$', data)
                    if msub.group(1) in RT_label[count]:
                        aa = count
                        bb = RT_label[count][msub.group(1)]
                        rtc[addr] = RT_offset[aa] + bb - int(msub.group(2)) - 1
                elif g1 in RT_label[count]:
                    if g3 is not None:
                        pass  # Perl prints "error" but continues
                    else:
                        aa, bb = count, RT_label[count][g1]
                        rtc[addr] = RT_offset[aa] + bb - 1
                else:
                    raise Mc2MbError('cannot execution %s' % data)

    # ---- convert units to output byte values --------------------------
    output_UT_dir = []
    for i in range(len(UT_dir)):
        out = {}
        for j in range(_maxidx(UT_dir[i]) + 1):
            if j in UT_dir[i]:
                out[j] = _put_inst_value(UT_dir[i][j], j)
        output_UT_dir.append(out)

    output_UT_indir = []
    for i in range(len(UT_indir)):
        out = {}
        for j in range(_maxidx(UT_indir[i]) + 1):
            if j in UT_indir[i]:
                v = UT_indir[i][j]
                if v == "NOOP":
                    out[j] = _NOP_LOOP_B[j % 94]
                else:
                    out[j] = _put_inst_value(v, j)
        output_UT_indir.append(out)

    # ---- BASE register ------------------------------------------------
    last = len(RT) - 1
    ROUTINE_MAX = RT_offset[last] + (_maxidx(RT[last]) + 1)
    UNIT_MAX = 0
    if len(output_UT_indir) >= 1:
        oi = len(output_UT_indir) - 1
        off = UT_indir_firstOffset + (oi * 94)
        ln = _maxidx(output_UT_indir[oi]) + 1
        UNIT_MAX = off + ln
    for i in range(len(RT_label)):
        for label, addr in RT_label[i].items():
            if label == "BASE":
                val = max(ROUTINE_MAX, UNIT_MAX) + 3
                if val % 2 == 0:
                    val += 1
                RT[i][addr] = val

    # ---- emit .data ---------------------------------------------------
    a2 = RT_name[startLABEL[0]]
    b2 = RT_label[a2][startLABEL[1]]
    startADDR = RT_offset[a2] + b2

    out = []
    out.append("ENTRY_ADDRESS:%d\r\n" % startADDR)

    for i in range(len(output_UT_dir)):
        tmp1 = UT_dir_firstOffset + i * 94
        tmp2 = _maxidx(output_UT_dir[i]) + 1
        out.append("DIRECT_UNIT_CODE:%d\r\n" % i)
        out.append("offset:%d\r\n" % tmp1)
        out.append("len:%d\r\n" % tmp2)
        for j in range(_maxidx(output_UT_dir[i]) + 1):
            if j in output_UT_dir[i]:
                out.append("%s\r\n" % output_UT_dir[i][j])
            else:
                out.append("%d\r\n" % data_dup)

    for i in range(len(RT)):
        tmp1 = RT_offset[i]
        tmp2 = _maxidx(RT[i]) + 1
        out.append("ROUTINE_CODE:%d\r\n" % i)
        out.append("offset:%d\r\n" % tmp1)
        out.append("len:%d\r\n" % tmp2)
        for j in range(_maxidx(RT[i]) + 1):
            if j in RT[i]:
                out.append("%s\r\n" % RT[i][j])
            else:
                out.append("%d\r\n" % data_dup)

    for i in range(len(output_UT_indir)):
        tmp1 = UT_indir_firstOffset + i * 94
        tmp2 = _maxidx(output_UT_indir[i]) + 1
        out.append("INDIRECT_UNIT_CODE:%d\r\n" % i)
        out.append("offset:%d\r\n" % tmp1)
        out.append("len:%d\r\n" % tmp2)
        for j in range(_maxidx(output_UT_indir[i]) + 1):
            if j in output_UT_indir[i]:
                out.append("%s\r\n" % output_UT_indir[i][j])
            else:
                out.append("%d\r\n" % data_dup)

    out.append("END\r\n")
    return "".join(out)


# ---------------------------------------------------------------------------
# Stage 2: init/{init,dmod,comm}.cpp -> .mb
# ---------------------------------------------------------------------------

# --- constants (init.h) ----------------------------------------------------
_MAX_CODE_SIZE = 3486784400
_CONST_1 = 1743392200
_PAT_20 = 3486784398
_PAT_21 = 3486784399

# op-list enum (init.h Operations)
(OP_NOOP, OP_DEST, OP_D_PTR, OP_CL_D_PTR, OP_MOV_DMOD0, OP_MOV_DMOD1,
 OP_CON0_PTR, OP_CON1_PTR, OP_CON2_PTR, OP_PAT20_PTR, OP_PAT21_PTR, OP_SELF_PTR,
 OP_ROT_PTR, OP_CON0, OP_CON1, OP_CON2, OP_PAT20, OP_PAT21, OP_SELF, OP_ROT,
 OP_CL_CON0, OP_CL_CON1, OP_CL_CON2, OP_CL_PAT20, OP_CL_PAT21, OP_CL_ROT,
 OP_TR_CON0, OP_TR_CON1, OP_TR_CON2, OP_TR_PAT20, OP_TR_PAT21, OP_TR_REGA,
 OP_DEST_CON0) = range(33)

# mem_op signals (dmod.cpp)
MM_DATA, MM_CON0, MM_CON1, MM_CON2, MM_PAT20 = -1, -2, -3, -4, -5

# data-module cell labels (dmod.cpp #defines)
M_DATA, M_RET0, M_LOD2, M_CON0, M_CON1, M_PT20, M_RET1 = 36, 37, 38, 39, 40, 41, 42
M_CON2, M_RET2, M_DCN0, M_LODX, M_RETX, M_LCN1, M_RETx = 43, 44, 45, 46, 47, 48, 49
M2_DATA, M2_RET0, M2_LOD2, M2_CON0, M2_CON1, M2_PT20, M2_RET1 = 54, 55, 56, 57, 58, 59, 60
M2_CON2, M2_RET2, M2_LODX = 61, 62, 63
M_ENTRY = 82

AC_ROT, AC_OPR = 0, 1
_DM_SEARCH_DEPTH = 3

# op(x,y) tables (comm.cpp)
_P9 = [1, 9, 81, 729, 6561, 59049, 531441, 4782969, 43046721, 387420489]
_OP_O = [
    [4, 3, 3, 1, 0, 0, 1, 0, 0],
    [4, 3, 5, 1, 0, 2, 1, 0, 2],
    [5, 5, 4, 2, 2, 1, 2, 2, 1],
    [4, 3, 3, 1, 0, 0, 7, 6, 6],
    [4, 3, 5, 1, 0, 2, 7, 6, 8],
    [5, 5, 4, 2, 2, 1, 8, 8, 7],
    [7, 6, 6, 7, 6, 6, 4, 3, 3],
    [7, 6, 8, 7, 6, 8, 4, 3, 5],
    [8, 8, 7, 8, 8, 7, 5, 5, 4],
]

_LEGAL = "ji*p</vo"


def _op(x, y):
    """comm.cpp op(x,y): 20-trit crazy operation."""
    i = 0
    for j in range(10):
        i += _OP_O[y // _P9[j] % 9][x // _P9[j] % 9] * _P9[j]
    return i


def _rot(x):
    """comm.cpp rot(x): 20-trit right rotate."""
    return x // 3 + x % 3 * 19683 * 59049


def _op_rev(dest):
    """init.cpp op_rev(dest): find x with op(x, CONST_1) == dest."""
    num = [1, 0, 2]
    ans = 0
    for i in range(20):
        ans += num[dest % 3] * (3 ** i)
        dest //= 3
    return ans


class _JmpAddrs(list):
    """``jmpaddrs`` with a mutation counter: ``dm_mov_search`` is a pure
    function of ``(d, pos, depth)`` for a fixed jmpaddrs state, so its results
    are memoised and the cache is invalidated whenever any slot is written."""

    def __init__(self, iterable):
        super().__init__(iterable)
        self.version = 0

    def __setitem__(self, index, value):
        self.version += 1
        super().__setitem__(index, value)


class _Assembler:
    """Port of the C++ ``init`` code generator (init/dmod/comm.cpp)."""

    def __init__(self):
        self.code = {}          # pos -> source byte (char array)
        self.code_size = 0
        self.C = 0
        self.D = 0
        self.jmpaddrs = _JmpAddrs([-1] * 100)
        self._dm_cache = {}
        self._dm_cache_version = -1
        self.dataLine = {}      # absolute addr -> value (default -1)
        self.using_dmod = 0
        self.dmod_ptr = -1

    # --- comm.cpp: setchr family ------------------------------------------
    def setchr(self, chr_, pos):
        if chr_ not in _LEGAL:
            raise Mc2MbError("Error! '%s' is not an instruction" % chr_)
        rc = _rev_xlat1_c(ord(chr_), pos)
        self.code[pos] = rc
        if pos + 1 > self.code_size:
            self.code_size = pos + 1
        return rc

    def setchr_C(self, chr_):
        rc = self.setchr(chr_, self.C)
        self.C += 1
        return rc

    def setchr_D(self, chr_):
        rc = self.setchr(chr_, self.D)
        self.D += 1
        return rc

    # --- dmod.cpp: D-register movement ------------------------------------
    def dm_mov_search(self, d, pos, depth=0):
        """Returns (min_noops, jpos)."""
        if self._dm_cache_version != self.jmpaddrs.version:
            self._dm_cache = {}
            self._dm_cache_version = self.jmpaddrs.version
        key = (d, pos, depth)
        cached = self._dm_cache.get(key)
        if cached is not None:
            return cached
        min_noops = -1
        jpos = -1
        if pos >= d:
            min_noops = pos - d
            jpos = -1
        if depth < _DM_SEARCH_DEPTH:
            for i in range(d, 100):
                if self.jmpaddrs[i] >= 0:
                    noops, _l = self.dm_mov_search(self.jmpaddrs[i] + 1, pos, depth + 1)
                    if noops != -1:
                        noops += i - d + 1
                        if min_noops == -1 or min_noops > noops:
                            min_noops = noops
                            jpos = i
        self._dm_cache[key] = (min_noops, jpos)
        return min_noops, jpos

    def dm_move(self, pos):
        num = 0
        if pos > _MAX_CODE_SIZE:
            raise Mc2MbError("Error! dm_move pos")
        min_noops, jpos = self.dm_mov_search(self.D, pos)
        if min_noops == -1:
            raise Mc2MbError("Error! unable to move (%d to %d)[%d]"
                             % (self.D, pos, self.C))
        if jpos != -1:
            while self.D < jpos:
                self.setchr_C('o')
                self.D += 1
                num += 1
            self.setchr_C('j')
            num += 1
            self.D = self.jmpaddrs[jpos] + 1
            num += self.dm_move(pos)
        else:
            while self.D < pos:
                self.setchr_C('o')
                self.D += 1
                num += 1
        return num

    def dm_accs(self, ac, pos):
        num = 0
        if ac == AC_ROT:
            num += self.dm_move(pos)
            self.setchr_C('*')
            num += 1
        elif ac == AC_OPR:
            num += self.dm_move(pos)
            self.setchr_C('p')
            num += 1
        self.D += 1
        return num

    def dm_move2(self, pos, signal=1):
        num = 0
        if signal < 0:
            mm_table = [[M_DATA, M_CON0, M_CON1, M_CON2, M_PT20],
                        [M2_DATA, M2_CON0, M2_CON1, M2_CON2, M2_PT20]]
            if self.using_dmod == -1:
                raise Mc2MbError("Error! unable to move (using_dmod==-1)")
            elif signal < -5:
                raise Mc2MbError("Error! unable to move (pos < -5)")
            pos = mm_table[self.using_dmod][-signal - 1]
        if pos < 100:
            num = self.dm_move(pos)
        else:
            raise Mc2MbError("Error! unable to move!")
        return num

    def dm_accs2(self, ac, pos, signal=1):
        num = 0
        if ac == AC_ROT:
            num += self.dm_move2(pos, signal)
            self.setchr_C('*')
            num += 1
        elif ac == AC_OPR:
            if pos >= 100:
                if self.dmod_ptr == -1 or pos - self.dmod_ptr > 100 or pos < self.dmod_ptr + 1:
                    raise Mc2MbError("Error! unable to move!! pos=%d dmod_ptr=%d"
                                     % (pos, self.dmod_ptr))
                num += self.dm_move(M_LODX)
                self.setchr_C('j')
                num += 1
                d = pos - (self.dmod_ptr + 1)
                for _ in range(d):
                    self.setchr_C('o')
                    num += 1
                self.setchr_C('p')
                num += 1
                if pos == _MAX_CODE_SIZE:
                    self.D = 0
                    self.setchr_C('o'); num += 1
                    self.setchr_C('o'); num += 1
                    self.setchr_C('j'); num += 1
                    self.setchr_C('o'); num += 1
                    self.setchr_C('o'); num += 1
                    self.D = M_ENTRY
                else:
                    if pos % 2 == 0:
                        self.setchr_C('o'); num += 1
                    self.setchr_C('j'); num += 1
                    self.D = M_ENTRY
                return num
            else:
                num += self.dm_move2(pos, signal)
                self.setchr_C('p')
                num += 1
        self.D += 1
        return num

    # --- dmod.cpp: op_decode ----------------------------------------------
    def op_decode(self, op_list, dest_pos=-1, d_ptr=-1):
        length = 0
        self.dmod_ptr = d_ptr
        if dest_pos != -1 and dest_pos < 100:
            raise Mc2MbError("Error! dest_pos (%d)" % dest_pos)

        A = self.dm_accs2
        for p in op_list:
            if p == OP_NOOP:
                return 0
            elif p == OP_DEST:
                length += A(AC_OPR, dest_pos)
            elif p == OP_D_PTR:
                length += A(AC_OPR, M_LODX)
                length += self.dm_move2(M_ENTRY)
            elif p == OP_CL_D_PTR:
                length += A(AC_ROT, M_LCN1)
                length += A(AC_OPR, M_LODX)
                length += A(AC_OPR, M_LODX)
                length += self.dm_move2(M_ENTRY)
            elif p == OP_MOV_DMOD0:
                self.using_dmod = 0
            elif p == OP_MOV_DMOD1:
                self.using_dmod = 0
            elif p == OP_CL_CON0:
                length += A(AC_ROT, M_DCN0)
                length += A(AC_OPR, dest_pos)
                length += A(AC_ROT, 0, MM_CON0)   # fallthrough to OP_CON0
                length += A(AC_OPR, 0, MM_DATA)
            elif p == OP_CON0:
                length += A(AC_ROT, 0, MM_CON0)
                length += A(AC_OPR, 0, MM_DATA)
            elif p == OP_CON0_PTR:
                length += A(AC_ROT, M_DCN0)
                length += A(AC_OPR, M_LODX)
            elif p == OP_CON1:
                length += A(AC_ROT, 0, MM_CON1)
                length += A(AC_OPR, 0, MM_DATA)
            elif p == OP_CON1_PTR:
                length += A(AC_ROT, M_LCN1)
                length += A(AC_OPR, M_LODX)
            elif p == OP_CL_CON2:
                length += A(AC_ROT, M_DCN0)
                length += A(AC_OPR, dest_pos)
                length += A(AC_ROT, 0, MM_CON2)   # fallthrough to OP_CON2
                length += A(AC_OPR, 0, MM_DATA)
            elif p == OP_CON2:
                length += A(AC_ROT, 0, MM_CON2)
                length += A(AC_OPR, 0, MM_DATA)
            elif p == OP_CON2_PTR:
                length += A(AC_ROT, M_CON2)
                length += A(AC_OPR, M_LODX)
            elif p == OP_CL_PAT20:
                length += A(AC_ROT, M_DCN0)
                length += A(AC_OPR, dest_pos)
                length += A(AC_ROT, 0, MM_CON1)   # fallthrough to OP_PAT20
                length += A(AC_OPR, 0, MM_PAT20)
                length += A(AC_OPR, 0, MM_DATA)
            elif p == OP_PAT20:
                length += A(AC_ROT, 0, MM_CON1)
                length += A(AC_OPR, 0, MM_PAT20)
                length += A(AC_OPR, 0, MM_DATA)
            elif p == OP_PAT20_PTR:
                length += A(AC_ROT, M_CON1)
                length += A(AC_OPR, M_PT20)
                length += A(AC_OPR, M_LODX)
            elif p == OP_CL_PAT21:
                length += A(AC_ROT, M_DCN0)
                length += A(AC_OPR, dest_pos)
                length += A(AC_ROT, 0, MM_CON0)   # fallthrough to OP_PAT21
                length += A(AC_OPR, 0, MM_PAT20)
                length += A(AC_OPR, 0, MM_DATA)
            elif p == OP_PAT21:
                length += A(AC_ROT, 0, MM_CON0)
                length += A(AC_OPR, 0, MM_PAT20)
                length += A(AC_OPR, 0, MM_DATA)
            elif p == OP_PAT21_PTR:
                length += A(AC_ROT, M_CON0)
                length += A(AC_OPR, M_PT20)
                length += A(AC_OPR, M_LODX)
            elif p == OP_SELF:
                length += A(AC_OPR, 0, MM_DATA)
            elif p == OP_SELF_PTR:
                length += A(AC_OPR, M_LODX)
            elif p == OP_CL_ROT:
                length += A(AC_ROT, M_DCN0)
                length += A(AC_OPR, dest_pos)
                length += A(AC_ROT, 0, MM_DATA)   # fallthrough to OP_ROT
            elif p == OP_ROT:
                length += A(AC_ROT, 0, MM_DATA)
            elif p == OP_ROT_PTR:
                length += A(AC_ROT, M_LODX)
            elif p == OP_CL_CON1:
                length += A(AC_ROT, M_DCN0)
                length += A(AC_OPR, dest_pos)
                length += A(AC_OPR, 0, MM_DATA)
            elif p == OP_TR_CON0:
                length += A(AC_ROT, M_DCN0)
            elif p == OP_TR_CON1:
                length += A(AC_ROT, M_LCN1)
            elif p == OP_TR_CON2:
                length += A(AC_ROT, 0, MM_CON2)
            elif p == OP_TR_PAT20:
                length += A(AC_ROT, 0, MM_CON1)
                length += A(AC_OPR, 0, MM_PAT20)
            elif p == OP_TR_PAT21:
                length += A(AC_ROT, 0, MM_CON0)
                length += A(AC_OPR, 0, MM_PAT20)
            elif p == OP_TR_REGA:
                pass
            elif p == OP_DEST_CON0:
                length += A(AC_ROT, M_DCN0)
                length += A(AC_OPR, dest_pos)

        self.dmod_ptr = -1
        self.using_dmod = 0
        return length

    # --- init.cpp: data-value code generators -----------------------------
    def var_generate(self, dest):
        op_list = [OP_CON1, OP_SELF]
        for _ in range(20):
            r = dest % 3
            if r == 0:
                op_list.append(OP_PAT21)
            elif r == 1:
                op_list.append(OP_CON2)
            else:
                op_list.append(OP_PAT20)
            op_list.append(OP_CON2)
            op_list.append(OP_ROT)
            dest //= 3
        return op_list

    def ptr_var_generate(self, dest):
        op_list = [OP_CL_D_PTR, OP_MOV_DMOD0]
        for _ in range(20):
            r = dest % 3
            if r == 0:
                op_list.append(OP_PAT21_PTR)
            elif r == 1:
                op_list.append(OP_CON2_PTR)
            else:
                op_list.append(OP_PAT20_PTR)
            op_list.append(OP_CON2_PTR)
            op_list.append(OP_ROT_PTR)
            dest //= 3
        return op_list

    def code_search(self, pos):
        length = 0
        op_list = self.ptr_var_generate(pos - 1)
        length += self.op_decode(op_list)
        dest = self.dataLine.get(pos, -1)
        x = _op_rev(dest)
        op_list = [OP_MOV_DMOD0, OP_DEST_CON0]
        op_list += self.var_generate(x)
        op_list.append(OP_DEST)
        length += self.op_decode(op_list, pos, pos - 1)
        return length

    def code_generate(self, start, size):
        for i in range(size):
            if self.dataLine.get(start + i, -1) != -1:
                self.code_search(start + i)

    # --- dmod.cpp: setup_data_module --------------------------------------
    def setup_data_module(self):
        self.C = self.setchr_C('i')
        self.setchr_C('o')
        self.D += 1
        self.D = self.setchr_D('j')
        self.setchr_C('j')
        self.D += 1

        for i in range(100):
            self.jmpaddrs[i] = -1
        self.jmpaddrs[42] = 39
        self.jmpaddrs[43] = 38
        self.jmpaddrs[44] = 89
        self.jmpaddrs[45] = 36
        self.jmpaddrs[46] = 35
        self.jmpaddrs[47] = 34
        self.jmpaddrs[48] = 33
        self.jmpaddrs[52] = 46
        self.jmpaddrs[53] = 81
        self.jmpaddrs[60] = 57
        self.jmpaddrs[61] = 56
        self.jmpaddrs[62] = 36
        self.jmpaddrs[63] = 54
        self.jmpaddrs[64] = 53
        self.jmpaddrs[84] = 50

        self.setchr('v', 2)
        self.setchr('/', 36)
        self.setchr('i', 37)
        self.setchr('v', 38)
        self.setchr('*', 39)
        self.setchr('i', 40)
        self.setchr('v', 41)
        self.setchr('v', 42)
        self.setchr('v', 43)
        self.setchr('*', 44)
        self.setchr('v', 45)
        self.setchr('v', 46)
        self.setchr('p', 47)
        self.setchr('v', 48)
        self.setchr('i', 49)
        self.setchr('*', 50)
        self.setchr('i', 52)
        self.setchr('j', 53)
        self.setchr('*', 54)
        self.setchr('j', 55)
        self.setchr('/', 56)
        self.setchr('v', 57)
        self.setchr('i', 58)
        self.setchr('i', 59)
        self.setchr('/', 60)
        self.setchr('/', 61)
        self.setchr('i', 62)
        self.setchr('/', 63)
        self.setchr('/', 64)
        self.setchr('/', 82)
        self.setchr('p', 83)
        self.setchr('j', 84)
        self.setchr('p', 3)
        self.jmpaddrs[3] = 59
        self.setchr('j', 4)
        self.jmpaddrs[4] = 36

        acR = lambda pos: self.dm_accs(AC_ROT, pos)
        acO = lambda pos: self.dm_accs(AC_OPR, pos)

        # 41 -> PAT21
        for _ in range(19):
            acR(40)
            acO(41)
        # 40 -> CON1
        acR(40)
        acO(40)
        acR(M_PT20)
        acO(40)
        acO(40)
        # 39 -> CON0
        acO(39)
        # 42 -> RET1
        self.jmpaddrs[42] = -1
        acO(M_PT20)
        acO(42)
        acR(M_PT20)
        acO(42)
        acR(M_PT20)
        acR(M_CON1)
        acO(M_PT20)
        acO(42)
        acR(M_CON0)
        acO(M_PT20)
        acR(M_PT20)
        acO(42)
        self.jmpaddrs[42] = 35

        for _ in range(15):
            acR(M_PT20)
        # 44 -> RET2
        self.jmpaddrs[44] = -1
        acO(44)
        acR(M_CON1)
        acO(M_PT20)
        acR(M_PT20)
        acO(44)
        self.jmpaddrs[44] = 35

        # 37 -> RET0
        acR(M_CON0)
        acO(M_PT20)
        acR(M_PT20)
        acR(M_PT20)
        acO(37)
        self.jmpaddrs[37] = 35

        acR(M_CON1)
        acO(M_PT20)
        # 38 -> LOD2
        acR(M_PT20)
        acO(38)
        acR(M_CON0)
        acO(M_PT20)
        acO(38)
        self.jmpaddrs[38] = 42

        # 47 -> RETX
        self.jmpaddrs[47] = -1
        acR(M_CON0)
        acO(M_PT20)
        acO(47)
        acR(M_CON0)
        acO(M_PT20)
        acO(47)
        acR(47)
        self.jmpaddrs[47] = 36

        # 49 -> RETx
        acR(M_DATA)
        acO(M_DATA)
        acO(49)
        self.jmpaddrs[49] = 45

        # 43 -> CON2
        acR(M_CON0)
        self.jmpaddrs[43] = -1
        acO(43)
        # 45 -> CON0
        self.jmpaddrs[45] = -1
        acO(45)
        acO(M_PT20)
        acO(43)

        # 48 -> CON1
        acR(M_CON1)
        self.jmpaddrs[48] = -1
        acO(48)
        acO(48)

        acR(M_CON1)
        acO(M_PT20)
        acO(46)
        self.jmpaddrs[46] = 59

        # _CON0 -> CON0
        acR(M_CON1)
        acO(57)
        # _CON1 -> CON1
        acO(58)

        # _PAT20 -> PAT21
        acR(M2_CON0)
        acO(59)
        acR(M_CON0)
        acO(M_PT20)
        acO(59)

        for _ in range(18):
            acR(M2_PT20)
        self.jmpaddrs[60] = -1
        acO(60)

        # 60 -> M2_RET1
        acR(M2_PT20)
        acO(60)
        acR(M2_PT20)
        acO(60)
        acR(M2_CON1)
        acO(M2_PT20)
        acO(60)
        acR(M2_CON0)
        self.jmpaddrs[61] = -1
        acO(61)
        acO(60)
        self.jmpaddrs[60] = 53

        # 55 -> M2_RET0
        acR(M2_CON0)
        acO(61)
        acO(55)
        self.jmpaddrs[55] = 53

        acR(M2_CON1)
        acO(61)
        self.jmpaddrs[61] = 56

        # 56 -> M2_LOD2
        acR(M2_CON0)
        acO(M2_PT20)
        acO(56)
        acR(M2_CON0)
        acO(M2_PT20)
        acO(56)
        self.jmpaddrs[56] = 60

        # 62 -> M2_RET2
        acR(M2_CON1)
        acO(M2_PT20)
        acO(M2_DATA)
        acO(M2_DATA)
        self.jmpaddrs[62] = -1
        acO(62)
        acR(M2_CON1)
        acO(M2_PT20)
        acO(62)
        acR(M2_CON0)
        self.jmpaddrs[61] = -1
        acO(61)
        acO(62)
        self.jmpaddrs[62] = 53
        acR(M2_CON1)
        acO(61)
        self.jmpaddrs[61] = 56

        for _ in range(18):
            acR(M2_PT20)
        acO(M2_DATA)
        self.jmpaddrs[63] = -1
        acO(63)
        acR(M2_CON1)
        acO(M2_PT20)
        acO(63)
        self.jmpaddrs[63] = 44

        # 61
        acR(M2_PT20)
        acR(M2_PT20)
        self.jmpaddrs[61] = -1
        acO(61)
        acR(M2_CON0)
        acO(61)
        acR(M2_CON0)
        acO(M2_PT20)
        acO(61)

        # 82,83 -> _RET0, RET0
        acO(82)
        acR(M_LCN1)
        acO(82)
        self.jmpaddrs[82] = M2_RET0 - 1

        acR(M_CON0)
        acO(M_PT20)
        acO(83)
        self.jmpaddrs[83] = M_RET0 - 1

        for _ in range(19):
            acR(M_DATA)
        acO(M_RETX)
        self.jmpaddrs[M_RETX] = 81

        self.dm_move(M_ENTRY)

    # --- init.cpp: memory_init_code1 --------------------------------------
    def memory_init_code1(self, data_text):
        lines = data_text.replace("\r\n", "\n").split("\n")
        n = len(lines)
        pos = [0]

        def nextline():
            if pos[0] >= n:
                return None
            ln = lines[pos[0]]
            pos[0] += 1
            return ln

        entryNum = None
        tmp = 0
        while pos[0] < n:
            line = nextline()
            if line is None:
                break
            if line.startswith("ENTRY_ADDRESS:"):
                entryNum = int(line[len("ENTRY_ADDRESS:"):])
            elif line.startswith("DIRECT_UNIT_CODE:"):
                l2 = nextline()
                if l2 is None or not l2.startswith("offset:"):
                    raise Mc2MbError("data file error. offset??")
                offset = int(l2[len("offset:"):])
                tmp = offset
                l3 = nextline()
                if l3 is None or not l3.startswith("len:"):
                    raise Mc2MbError("data file error.len??")
                dataLen = int(l3[len("len:"):])
                for i in range(offset, offset + dataLen):
                    dv = nextline()
                    if dv is None:
                        raise Mc2MbError("data file error!!")
                    dataNum = int(dv)
                    if 32 < dataNum < 127:
                        c = chr(_xlat1(dataNum, i))
                        self.setchr(c, i)
            elif line.startswith("ROUTINE_CODE:") or line.startswith("INDIRECT_UNIT_CODE:"):
                l2 = nextline()
                if l2 is None or not l2.startswith("offset:"):
                    raise Mc2MbError("data file error")
                offset = int(l2.rsplit(":", 1)[1])
                l3 = nextline()
                if l3 is None or not l3.startswith("len:"):
                    raise Mc2MbError("data file error")
                dataLen = int(l3[len("len:"):])
                for k in range(dataLen):
                    dv = nextline()
                    if dv is None:
                        raise Mc2MbError("data file error")
                    self.dataLine[offset + k] = int(dv)
                self.code_generate(offset, dataLen)
            # "END" and anything else: ignore

        # final-address adjustment (0-branch)
        self.dataLine[59048 * 59049 + 59046] = 74
        self.dataLine[59048 * 59049 + 59047] = 74
        self.dataLine[59048 * 59049 + 59048] = 74
        self.code_generate(3486784398, 3)

        # set M1_DATA to BIN_CODE_ENTRY
        dest = entryNum - 1
        op_list = [OP_MOV_DMOD0] + self.var_generate(dest)
        self.op_decode(op_list)

        self.dm_move(36)
        self.setchr_C('j')
        self.setchr_C('i')
        if self.C > tmp:
            raise Mc2MbError(
                "error: Direct unit has been destroyed by the code rewrite "
                "indirect instruction. Due to offset??")

    # --- init.cpp: main tail ----------------------------------------------
    def finish(self):
        # advance to an odd position whose Xlat1(82,pos) is a legal opcode
        while (chr(_xlat1(82, self.code_size)) not in _LEGAL) or not (self.code_size & 1):
            self.code_size += 1
        self.code[self.code_size] = 82
        self.code_size += 1
        self.code[self.code_size] = 81
        self.code_size += 1

        # fill unset cells deterministically (upstream uses srand(time)+rand()%8)
        for i in range(self.code_size):
            if not self.code.get(i):
                nch = _LEGAL[i % 8]
                self.code[i] = _rev_xlat1_c(ord(nch), i)

        return "".join(chr(self.code.get(i, 0)) for i in range(self.code_size))


def data_to_mb(data_text: str) -> str:
    """Port of the C++ ``init``: Malbolge20 ``.data`` memory image -> ``.mb``.

    Padding is filled deterministically (see module docstring), so the result
    is behaviourally equivalent to upstream ``init`` but not byte-identical.
    """
    asm = _Assembler()
    asm.setup_data_module()
    asm.memory_init_code1(data_text)
    return asm.finish()


def assemble_mc_to_mb(mc_source: str) -> str:
    """Assemble LAL (.mc) source into a Malbolge20 (.mb) program string."""
    data_text = parse_mc_to_data(mc_source)
    return data_to_mb(data_text)
