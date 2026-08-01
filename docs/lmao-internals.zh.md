# LMAO 内部算法分析(v0.6.0)

> [English](lmao-internals.md) | **中文**

> 依据 `ref/LMAO/src/` 约 4500 行有效 C 代码逐模块分析,作为 Python 移植的算法参考。
> 整理日期:2026-07-20。文中 `文件:行号` 均指 `ref/LMAO/src/` 下的文件。

## 0. 预备:Malbolge 语义与依赖常量(malbolge.h/malbolge.c)

- 内存 59049 = 3^10 格,10-trit 值 [0, C2]。常量 C0=0, C1=29524, C2=59048, C21=59047, C20=59046。
- 指令 = `(mem[C]+C) % 94`:Jmp=4, Out=5, In=23, Rot=39, MovD=40, Opr=62, Nop=68, Hlt=81(malbolge.h:38-103);其余值全当 Nop(xlat.c:26)。
- `crazy(a,d)` = 逐 trit 查表 `crz[a%3 + 3*(d%3)]`,crz={1,0,0,1,0,2,2,2,1}(malbolge.c:25)。Opr 做 `[D]=A=crazy(A,[D])`。
- `rotate_right(d) = d/3 + (d%3)*19683`(malbolge.c:46)。Rot 做 `[D]=A=rotate_right([D])`。
- 自加密:每条指令执行后 `mem[C] = XLAT2[mem[C]-33]`(XLAT2 表见 malbolge.h:113)。一格想重复执行相同语义,必须在 XLAT2 轨道上循环回自身——这是汇编器的核心对抗对象。
- 合法源字符:`(pos+c) % 94` ∈ 8 个 opcode 且 c ∈ [33,126](xlat.c:36 `is_valid_initial_character`)。

**核心洞察**:多数内存字既非合法源字符、又需要精确的 10-trit 值,必须在运行时用 Rot/Opr 从少数常量格"算"出来。汇编器绝大部分复杂度都在自举生成器(§5)。

## 1. 整体流水线(main.c:45-396)

1. `parse_input_args`(cli.c:42):`-o/-f/-l/-d`。默认 `.hell` → `.mb`。
2. `yyparse()`:构造三个全局结构——labeltree(标签 BST)、datablocks、codeblocks(块链头数组,globals.h)。
3. 取 ENTRY 标签(main.c:96):必须是 .DATA 标签,值 = 要跳入的代码地址。
4. `handle_u_and_r_prefixes`(§3)。
5. 分配 4 个 `MemoryCell[59049]`:preinitialized_section / to_be_initialized_section / fixed_offsets / memory_layout,全置 UNUSED。
6. 代码块路由(main.c:119-200):计算 `possible_positions[94]` + 判定 `needs_initialization`,分流:.OFFSET→fixed;需运行时构造→toinitial;可直接嵌入源文件→preinitial。调 `add_codeblock_to_memory_layout`。
7. 数据块路由(main.c:203):.OFFSET→fixed,否则→toinitial。
8. 装配主循环(main.c:228-328,带尺寸估计):`put_all_memcells_together` → `update_offsets` → `generate_opcodes_from_memory_layout` → `generate_malbolge_initialization_code`;失败则 `initialize_code_size += 32` 重试;fast_mode 直接用满内存,失败自动回退普通模式。
9. 输出 smaller_program(可折行)+ 调试文件(`-d`)。

### 核心 struct(types.h / gen_init.h)

| struct | 位置 | 内容 |
|---|---|---|
| XlatCycle | types.h:59 | 一格的 xlat2 循环链表;循环抵抗 NOP:`next==self`;单次序列末尾 `next==NULL` |
| DataAtom | types.h:72 | 常量或标签引用;`number==1`→R_ 前缀;`operand_label` 非空→U_ 前缀待解析;-1 未用,-2 don't-care |
| DataCell | types.h:122 | 值表达式树(LEAF/PLUS/MINUS/TIMES/DIVIDE/ROTATE_R/L/CRAZY/DONTCARE/NOT_USED) |
| Data/CodeBlock | types.h:132/150 | 连续格双向链表,offset(-1 未定),CodeBlock 有 `virtual_block`(U_ 合成的虚拟 NOP) |
| LabelTree | types.h:174 | 名 → code 或 data 块 |
| MemoryCell | types.h:236 | {code, data, usage},usage ∈ UNUSED/PREINITIALIZED_CODE/CODE/DATA/RESERVED_CODE/RESERVED_DATA |
| DRegPos/Cell/Module/State | gen_init.h:55-141 | 自举生成器的虚拟机镜像(§5) |

## 2. xlat 循环(xlat.c + main.c:119-200)

HeLL 里 `Opr/Nop`、`Nop/MovD` 等,`/` 分隔 = 该格被反复执行时依次表现的指令序列(沿 XLAT2 轨道走)。可用条件:存在起始字符 c 使 `(c+pos)%94` 给出序列首指令,沿 XLAT2 依次得到各指令,走完后闭合回起始字符。

`is_xlatcycle_existent`(xlat.c:55-141):
- `next==NULL`(单指令只执行一次):任意位置可放,直接反解字符。
- 跳过前导 NOP 计数;纯 NOP(RNop)查 `immutable_nops[position]` 表(Lou Scheffer 的不动 NOP,xlat.c:96)。
- 否则沿 XLAT2 逐步校验:is_nop 属性处处一致 + 非 NOP 操作码精确相等,验尾部 NOP 前缀 + 闭合。

main.c:130-176 `possible_positions[94]`:94 个残基初值 2(可嵌入源文件)/0;逐格沿 cycle:不存在→0;原为 2 但起始字符非合法源字符→降为 1(必须运行时构造);全部无法保持 2 → `needs_initialization=1`。pos 每格 +1 保证连续残基。

## 3. 前缀解析(prefix.c)

解析器已区分三种形式(lmao.y:496):普通(number=0)、`R_label`(number=1)、`U_label operand`(operand_label 非空)。

`resolve_prefix_for_dataatom`(prefix.c:43-204):
- **普通标签**:仅校验存在;取值 = `label.offset + number` 再 -1(补偿 Jmp/MovD 后 C/D 自增,求值在 initialize.c:82)。
- **`R_label`**(prefix.c:156):后继格(地址+1,再经统一 -1 → 净值为地址本身)。用于执行完某 xlat 指令后"恢复"它(典型:`R_CRAZY R_MOVED`)。校验 `dest->next != NULL`。
- **`U_label operand`**(prefix.c:48-154,最复杂):从本格后继沿链前走到 operand 所在 DataBlock,得负偏移(必须同一连续数据块);写入 number;再在目标代码标签前合成 |offset| 个虚拟循环抵抗 NOP CodeBlock(能复用已有前导 NOP,否则新建 `virtual_block=1`)。用途:构造 MovD 目标,使跳到它时先跑一串 NOP,NOP 数 = operand 在块内的位置——实现"用 D 指针移动步数判定值"(cat 示例的 EOF 检测)。

最后 `handle_u_and_r_prefixes` 把 codeblocks 各链头沿 prev 回退到真正的头(虚拟 NOP 可能加在前面)。

## 4. 内存布局(layout.c + main.c)

三分区 + 贪心首次适配(**非回溯**):

- `add_codeblock`(layout.c:28-137):有 .OFFSET 则在 offset-1 放 RESERVED_CODE 前哨,逐格放 CODE/PREINIT,mod 环绕,重叠即失败;相对块则 try_pos 从 1 起(0 留给前哨)前进到 `possible_positions` 允许的残基,要求前一格空 + 整块空,首个满足即放。贪心取最低位,不回溯。
- `add_datablock`(layout.c:139):类似,try_pos 从 0 起,NOT_USED 格跳过(允许重叠复用),DONTCARE→RESERVED_DATA。

`put_all_memcells_together`(layout.c:218-364,最微妙),产出地址几何(低→高):

1. 复制 fixed_offsets,记录 last_toinitial / last_preinitial。
2. 放 toinitial 区:对齐相对 C2 的 mod-94 边界,起点靠内存顶端(C2-...),冲突则 -=94 下滑 → **运行时构造的格全在高地址(近 59048)**。
3. 定位 **RQ**:从 startoffset-2 向下找残基 ∈ {16,17,35,51,52,74,80,93} 且相邻两格非 PREINIT 的位置,须 ≥500,clamp 到 end_of_init_code+1。`last_preinitialized_cell = RQ+1`。
4. 放 preinitial 区:紧贴 RQ 之下,mod-94 对齐,冲突下滑。

**RQ 的作用**:源文件只写到 RQ(程序长度 = last_preinitialized+1),`'R''Q'` 是源码末两个字符(initialize.c:453)。Malbolge 装载后,超出程序长度的格由末两格反复 crazy 填充;R、Q 的选定使无限填充恰好产生生成器假设的 `81 / (C1-81)` 按地址奇偶交替的图案。高地址的运行时构造格不出现在源文件里。

尺寸估计(main.c:228):`end_of_init_code` 是自举代码长度上界,决定 RQ 放多高;失败则 +=32 重试(启发式收敛,非精确)。

## 5. 初始化代码生成(gen_init.c + initialize.c,最核心)

思路:只用 Rot/Opr 对少数常量格做运算、用 MovD/Jmp 驱动 D 指针,在运行时把任意格写成任意值。

### 数据模块系统(State,gen_init.h:125 / initialize.c:286)

4 个模块,State 静态镜像全部格值,**无需真跑解释器即可预测 A/D/各格值**:

- **模块 0 = 协调器**(15 格,绝对地址 82-96):cell0=C0,cell5=C1,cell6=TMP,cell7-10=进位掩码,cell11=C2,cell12=DESTINATION(写入目标指针),其余 PTR。
- **模块 1/2/3 = 值生成器**(各 8 格,绝对 33-40 / 48-55 / 71-78,内存图见 ref/LMAO/datamodule.txt):cell0=C0,cell1=C1,cell2=C21,cell3=VAR(常量累加器),cell4=C2,cell5-7=PTR。暖启动值 VALUE1=126,VALUE2=58688,VALUE3=29495。
- **魔法初值**:INIT_A_REG=58328,INIT_POS_IN_MOD=8,INIT_DEST_VAL=68,INIT_TMP_VAL=C1(initialize.c:224)——与 init_datamodule 前缀字符串一一绑定,**不可独立更改,只能连同前缀照抄**。
- Cell.type 约束合法运算:PTR/CONST 不能被 crazy;C20_OR_C21 只能与 C0/C1 crazy;Rot 只作用于 VAR 或 C0/C1/C2。

### 归一化 opcode(denormalize 表 gen_init.c:909)

`o`=Nop(68), `j`=MovD(40), `p`=Opr(62), `*`=Rot(39), `i`=Jmp(4), `<`=Out, `/`=In, `v`=Hlt。注意反直觉:o 是 Nop(D 前进一格),j 是 MovD(沿 PTR 跳)。

`add_to_init_code`(gen_init.c:269-512):对每个发射的归一化字符,在 State 上模拟其对 D/A/格值的影响(o:D++ 环绕、遇 82 进模块 0;j:跟随 PTR 或退出到绝对地址;p:`A=cell=crazy(A,cell)` 且 D++;*:rotate 同理)。这套镜像是生成器能静态推理的基础。

`set_dreg`(gen_init.c:515-663):把 D 移到 (module, pos):同模块用 o 步进 / 遇 PTR 用 j 抄近路;跨模块必经模块 0 中转;递归实现。

### 常量/地址合成(核心数学)

- `get_register_a_value_for_crazy`(gen_init.c:136):求 A 使 `crazy(A,source)==dest`,逐 trit 优先复用当前 A 的 trit;无解返回 0xFFFF(crazy 对 A 非满射)。先特判 C0/C1/C2/C2-1/C2-2。
- `get_best_register_a_value_for_crazy`(gen_init.c:209):在 0-9 次旋转 × 是否先 crazy C2 之间挑最省方案,代价 `cost = diff*9 + rotations*3 (+2 若先 C2)`。
- `load_constant_to_a_reg`(gen_init.c:701):物化常量进 A。平凡常量直接取格;否则在 cell3(VAR)上逐 trit 合成(trit=0 用 Opr C20 / trit=1 用 Opr C21 / trit=2 不动 + c2_outstanding),配合 Rot 走完 10 个 trit。可复用上次常量。
- `get_module_for_constant_generation`(gen_init.c:688):值 ≤161 用模块 3 / ≤last_preinit 用模块 1 / 否则模块 2。
- `increment_destination_by_9`(gen_init.c:851):因按地址升序写,下一目标常在 +1..9 内,用 TMP + 进位掩码格对 DESTINATION 做三进制 +9,比重算地址便宜。

### 单格驱动 `generate_normalized_init_code_for_word`(gen_init.c:945-1075)

1. `old_mem_val` =(与 last_preinitialized 同奇偶 ? 81 : C1-81)——该高地址格的默认值(来自 RQ 填充图案)。等于目标值则跳过。
2. 生成目标地址:重算 DESTINATION(把 cell12 变成 init_position-1)/ INCREMENT_BY_9 / 已够近;crazy 无解则先把 cell12 crazy 到 C1 重试。
3. 计算写入常量;无解则先把目标格 crazy C0 清成 C1 重试。
4. 发射:LOAD_CONSTANT 进 A → SET_DREG(0,12) 后 j(MovD 到 DEST,D=init_position-1 再 D++)→ 若干 o 走到 init_position → p(Opr 写入 `crazy(A,cell)=init_value`)。

### 顶层组装 `generate_malbolge_initialization_code`(initialize.c:236-487)

1. 缓冲区先放 **init_datamodule 字面前缀**(initialize.c:246,逐字复制、不可再生,在绝对 33-96 铺数据模块,同时决定 State 初值)。
2. 对 last_preinitialized+1..C2 每个需写格,按**地址升序**调单格驱动。
3. `generate_jump_to_entrypoint`(gen_init.c:1079):生成 ENTRY 地址、MovD 到 DEST、走 o 到 entry 格。
4. 在 `59049-size_left` 处放 i(Jmp)跳入 HeLL 程序;`execution_steps = 该位置 - 98`(98 = "bP"2 格 + 96 模块区)。
5. i 与 RQ 之间用 `"i</*jpov"` 随机 NOP 填充(不会被执行)。
6. 重叠检查:用户格不得压 [2, init 末] 及 RQ 两格。
7. `denormalize_malbolge`:转真实源字符 `code = (instr + 94 - c%94) % 94`,<33 则 +94。
8. 写 'R''Q';cell0-1 强制 "bP";允许预初始化格替换填充区。

**入口交接**:ENTRY 是数据格,存首条代码地址(标签引用已 -1)。启动时 D 指向 ENTRY 附近由初始化代码接管;初始化末尾的 i(Jmp)使 `C=[D]=代码地址`,控制转入 HeLL 程序。

## 6. 输出编码(initialize.c)

最终源文件 = init_datamodule 字面前缀 + 反归一化自举代码 + i + 随机 NOP 填充 + RQ。高地址格纯运行时构造,不在源文件中。

`generate_opcodes_from_memory_layout`(initialize.c:171):CODE/PREINIT 格用 `is_xlatcycle_existent` 求出的起始字符;DATA 格用 `parse_datacell` 求值(递归表达式树);RESERVED_CODE 用安全值(81 / 最近合法 opcode 按奇偶);UNUSED/RESERVED_DATA 给 -1(don't-care,输出时填任意合法字符)。

## 7. Python 移植要点

**可以简化**:
- 前端不用 flex/bison:手写 tokenizer + 递归下降(优先级外→内:`>> <<`、`!`、`+ -`、`* /`,带括号)。
- BST → dict;链表块 → list + 下标;DataCell 树 → 递归求值。
- 主循环 += 32 收敛可换二分或激进初值。

**必须原样保留**(任何偏差都会产出错误的 Malbolge):
- crazy 表 / rotate_right / XLAT2 表 / 8 opcode 残基 / `is_valid_initial_character` 集合 / xlat 轨道逻辑 / immutable_nops 表。
- **init_datamodule 前缀逐字节照抄** + 绑定的 INIT_A_REG=58328 等 State 初值与模块布局(魔法常量不能重新推导,只能复制)。
- 代价模型 / load_constant 逐 trit 合成 / set_dreg 导航 / add_to_init_code 状态机 / denormalize 公式 / put_all_memcells 对齐数学 / RQ 残基集 {16,17,35,51,52,74,80,93}。

**陷阱**:
- "-1 自增补偿"无处不在;
- old_mem_val 的 81/(C1-81) 奇偶假设依赖 RQ 填充种子;
- D 的 o 步进到绝对 82 会掉进模块 0,跨模块必须经模块 0;
- execution_steps 的 98(= 2 + 96);
- 归一化字符反直觉(o=Nop,j=MovD,i=Jmp);
- 终极验证手段:把产物喂给 pyMalbolge 解释器与 LMAO 产物对拍。

**难度排序**(难→易):
1. gen_init 常量/地址合成 + set_dreg + add_to_init_code 状态模拟(最难,须与模块布局逐比特吻合);
2. put_all_memcells 对齐 + RQ 定位 + 尺寸驱动(off-by-one 陷阱密集);
3. xlat 存在性 + possible_positions;
4. U_/R_ 前缀 + 虚拟 NOP 合成;
5. 解析器(上下文相关 `/`、`{}` 抑制 EMPTYLINE、require_whitespace、`? ?- @`);
6. denormalize + 输出。
