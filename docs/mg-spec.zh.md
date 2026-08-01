# .mg(制御付き疑似命令列)语言规格

> [English](mg-spec.md) | **中文**

> 本文档依据 `ref/nagoya-ternary/scanner.ll`、`parser.yy`、`CodeBlock.cc`、`Routine.cc`、
> `Program.cc`、`Variable.cc`、`Radix.cc`、`Option.cc`/`main.cc` 逐行核对整理,并与
> 2016 年中间语言原始论文(河邉ほか,"難読性の高い Malbolge コードを生成するコンパイラ
> のための中間言語", IEICE Tech. Rep. SS2016-12)、2017 年函数扩展论文(坂梨ほか,
> "再帰呼び出しを持つ C 言語サブセットから Malbolge へのコンパイラ", IEICE Tech. Rep.
> SS2017-18)、`ref/nagoya-ternary/README.en.md`、`test/fixtures/nagoya/mg_*.mg` 五个
> 示例逐条对照,并用 `ref/nagoya-ternary/parser`(该工具本体)对约 20 个不确定语法点做了
> 实际编译实验(见文末"实验验证过的语法点"及各节脚注)。
> 作为 pyMalbolge 的 Python 版 `.mg`(→ .mc 低级汇编)编译器后端的实现依据。
> 整理日期:2026-07-20。

`.mg` 是"制御付き疑似命令列"(pseudo-instruction sequences with control,以下简称
"疑似命令列")的源文件后缀,是 `ref/nagoya-ternary/parser` 工具的输入语言,编译目标是
"低级汇编语言"(Low-Level-Assembly,`.mc`),再经 `ref/nagoya-lowass` 工具链变换为可
运行的 Malbolge20 程序(`.mb`)。完整管线见 `scripts/mg2mb.sh`。

---

## 一、词法(来自 `scanner.ll`)

### 1.1 标识符与关键字

- 标识符:`[a-zA-Z][0-9a-zA-Z_]*`,大小写敏感,长度无限制。
- 以下均为**保留字 token**,按精确匹配优先于一般标识符规则(flex 最长匹配语义下,
  只有与关键字**完全等长**的输入才会被识别为关键字;更长的标识符如 `CON00`、
  `RETURN_VALUE` 仍正常按 IDENT 解析,不受影响):
  `DEF VAR FLAG OPR ROT SET RESET END IF ELSE REPEAT BREAK SWITCH CASE0 CASE1
  CASE2 OUTPUT INPUT TRUE FALSE INF GOTO IND_OPR CALL RETURN PROTO FLIP CON0
  CON1 CON2 BASE RETURN_ADDR`。
  因此变量/routine 名不能**恰好**是这些词(含 `CON0`/`BASE`/`RETURN_ADDR` 这类看似
  可用的名字),但 `MyCon0`、`baseAddr` 等没有问题。
- 语法分析阶段会把用户标识符自动加前缀 `U_`(`escaped_ident: IDENT {$$ = "U_"+$1;}`),
  避免与生成的低级汇编内部标签冲突;这一点在 `.mg` 源码层不可见,写代码时无需关心。

### 1.2 数值字面量

`number` 产生式(`parser.yy:83-85`)只接受两种**字面量**,不支持任何表达式/运算符/变量:

| 记法 | 正则(scanner.ll) | 语义 |
|---|---|---|
| 十进制 | `[0-9]\|[1-9][0-9]*` | 单个 `0`,或不含前导零的十进制数。**`007` 这类带前导零的多位数是词法错误**(实测:被拆成 `0`/`0`/`7` 三个 token,报 `syntax error`)。 |
| 三进制 | `[0-9]+t` | 去掉尾部 `t` 后,按 `Radix::to(s, 3)` 解释:从左到右 `sm = sm*3 + digit`。**⚠ 正则允许任意 `0-9` 数字字符,解释时并不校验每位 ≤ 2**——例如 `39t` 会被当作合法字面量,计算出 `3*3+9=18`(实测确认,无报错、无警告)。这是记法为"三进制"但词法层完全不做位值校验的一个陷阱,Python 实现建议主动校验每位 ∈ {0,1,2} 并报错,而不是复刻这一疏漏。 |

两种记法算出的都是一个 `long long` 整数,**没有任何上界检查**(`Radix.cc` 全程无溢出/
范围判断)。CLAUDE.md 中"数值非负 ≤ 3^20-1"是 Malbolge20 一字长(20 trit)的硬件约束,
但 **`.mg` 编译器本身完全不做这个校验**——写入越界值会静默产生错误结果,需由使用者
(或未来的 Python 后端)自行把关。也不支持负数字面量(词法/语法都没有一元负号)。

### 1.3 注释与空白

- 行注释:`#` 到行尾(`#[^\n]+`)。没有块注释。
- 空白:空格、制表符、换行都会被跳过,对语句边界没有语义意义(不像 HeLL 的空行分块)。

### 1.4 未知字符

任何未匹配以上规则的字符,scanner 只打印 `cannot handle such characters: %s` 到 stderr
并**继续扫描**(不是致命错误,后续多半会级联出真正的语法错误)。

---

## 二、语法(依据 `parser.yy`)

```ebnf
program              ::= global_var_flag_decl* prototype* routine+

global_var_flag_decl ::= var_decl
                        | "FLAG" IDENT "=" bool_const

prototype             ::= "PROTO" IDENT

routine               ::= "DEF" IDENT var_decl* block "END"

var_decl              ::= "VAR" IDENT "=" number          /* number: 见 1.2, 仅字面量 */

block                 ::= statement*

statement              ::= "OPR" variable
                        | "ROT" variable
                        | "IND_OPR" variable
                        | "OUTPUT"
                        | "INPUT"
                        | "SET" flag
                        | "RESET" flag
                        | "FLIP" flag
                        | "IF" flag block "ELSE" block "END"
                        | "REPEAT" repeat_number block "END"
                        | "BREAK" [number]
                        | "SWITCH" variable case0 case1 case2 "END"
                        | "CALL" IDENT
                        | "RETURN"

repeat_number          ::= number | "INF"

case0                  ::= ("CASE0" block)?      /* 缺省 = 空块,允许省略某个 CASE */
case1                  ::= ("CASE1" block)?
case2                  ::= ("CASE2" block)?

variable                ::= variable_str
                          | variable_str "@" IDENT        /* 跨 routine 引用 */
variable_str             ::= IDENT | "CON0" | "CON1" | "CON2" | "BASE" | "RETURN_ADDR"

flag                    ::= IDENT
```

**关键、容易搞错的一点**:2016/2017 两篇论文的表格里用 `IFEND`、`REPEATEND`、
`SWITCHEND` 作为"概念上"的结束记号,但那只是论文行文的助记写法——**实际的
scanner/parser 里根本没有 `IFEND`/`REPEATEND`/`SWITCHEND` 这几个 token**
(`scanner.ll` 通篇搜不到)。`IF...ELSE...END`、`REPEAT...END`、`SWITCH...END`、
`DEF...END` 四种块**全部复用同一个 `END` 关键字收尾**,靠 LALR 语法结构(而不是不同的
关键字)区分嵌套配对。写 `.mg` 源码、或在 Python 里写词法/语法表时,只能有一个 `END`
token。(已用 `ref/nagoya-ternary/parser` 实测验证:写 `SWITCHEND` 会报
`syntax error`,写 `END` 才能通过。)

CASE0/CASE1/CASE2 三个分支均可省略(省略即空块),且顺序被语法**强制**为
`CASE0 → CASE1 → CASE2`(产生式顺序固定),不能颠倒或省略中间标签(比如没有 CASE1 只
写 CASE0/CASE2 不行,除非把 CASE1 干脆整段不写,由空产生式接管——但已经出现的
CASE0/CASE2 之间物理顺序仍必须是 0,1,2)。

`prototypes` 必须整体出现在**所有** `routine` 之前(即 `PROTO` 不能夹在两个 `DEF`
之间),这是文法结构决定的,不是风格建议。

---

## 三、程序结构与作用域

### 3.1 全局 vs. 例程局部

- `program` 顶层(所有 `DEF` 之前)允许两类声明:全局 `VAR`(进入内部的 `GLOBAL`
  伪例程)和全局 `FLAG`。
- **`FLAG` 只能在顶层声明**,不能出现在 `DEF...END` 内部——语法层面根本没有这条产生式
  (实测:`DEF MAIN FLAG F = TRUE ... END` 直接 `syntax error`)。所有 flag 天生是
  全局的。
- 一个 `DEF...END` 内部,`VAR` 声明必须**全部集中在该例程最开头、任何语句之前**
  (`var_decl_list` 产生式在 `block` 之前,不能穿插)。实测:在 `OUTPUT` 之后再写
  `VAR X = 5` 会报 `syntax error`,不是"允许但作用域局限"。
- 变量名解析规则(`parser.yy:150-160`):裸写 `X` 时,先在当前例程的局部变量里找,找不
  到再去全局(`GLOBAL`)例程里找,还找不到就是 `Undefined variable` 语义错误。**局部
  变量会遮蔽同名全局变量**。
- 跨例程引用外例程的**局部**变量,必须写 `X@例程名`(`variable_str AT IDENT`)。若目标
  例程当时还没定义该变量,解析器会**提前建一个占位变量**(`is_defined=false`),要求
  该例程后续必须用 `VAR X = ...` 真正定义它,否则在最终 `generate()` 阶段报
  `Variable 'X@例程名' is not defined.`。这使得"MAIN 引用 SUB 里稍后才声明的变量"
  在写法上是合法的前向引用(已实测通过)。

### 3.2 内建全局标识符:`CON0` / `CON1` / `CON2` / `BASE` / `RETURN_ADDR`

这五个不是用户标识符,而是词法层的专属 token(`scanner.ll:54-68`),对应
`Program` 构造函数(`Program.cc:3-17`)自动创建的全局变量(Malbolge20,20 trit 字宽):

| 名字 | 值 | 备注 |
|---|---|---|
| `CON0` | `0` | |
| `CON1` | `1743392200` | `= (3^20-1)/2`,内部用于 `CALL`/`RETURN` 地址运算 |
| `CON2` | `3486784400` | `= 3^20-1`,即 20 个 trit 全为 2 的"全 2 值",`SWITCH` 的合法取值都紧邻它(见 5.6) |
| `BASE` | `0` | |

普通 `.mg` 程序一般不需要直接用它们(它们主要是编译器内部生成 `CALL`/`RETURN`/`SWITCH`
代码时借用的公共常量),但语法层允许把它们当普通变量传给 `ROT`/`OPR`(`test/fixtures/
nagoya/mg_e_call.mc` 展示了 `ROT CON2 / OPR CONST_x` 这种"用 CON2 做减法"的手写习惯
写法,来自 `sample/hello-transFrom-c.mg`)。`RETURN_ADDR` 只有配合 `@例程名` 才有意义
(引用某例程内部保存返回地址的变量),裸写 `RETURN_ADDR`(不accompanied by `@`)会指向
"当前例程自己的" `RETURN_ADDR`,而只有非 `MAIN`/`GLOBAL` 的例程才会自动拥有这个变量
(`Routine.cc:9-11`)。

---

## 四、指令语义

以下语义综合自 2016 论文表 4/5(基础疑似命令 + 控制命令)、2017 论文表 7(含函数/
`IND_OPR` 扩展)与源码实现,并逐条标注与 `malbolge/core.py` 现有实现的对应关系。
`A` 表示 Malbolge 累加寄存器,`X`/`[X]` 表示变量 `X` 对应的内存单元当前值。

### 4.1 `ROT X` —— 原地旋转

**`A, [X] := rotr([X])`**:取 `X` 当前值,做一次 Malbolge 原生的"右旋转"(即
`malbolge/core.py` 的 `rotate()`,把 20 个 trit 整体循环右移一位,不是任意位数移
位),结果**同时**写回 `A` 寄存器和 `X` 所在内存(**原地修改**,不是只读)。

⚠ 因此 `ROT X` 是有副作用的:同一个变量在循环体内每 `ROT` 一次,其值就永久旋转一次。
`test/fixtures/nagoya/mg_d_repeat.mg` 的注释专门提醒了这一点——想要反复输出同一个
值,应在循环外 `ROT` 一次拿到 `A`,循环内只用不改变 `A` 的 `OUTPUT`。

### 4.2 `OPR X` —— crazy 运算

**`A, [X] := crazy(A, [X])`**,`crazy` 就是 `malbolge/core.py:crazy(a, b, trit_width)`
同一张表(`Malbolge` 原生 `OPR`/`p` 指令的三进制逐位真值表),这里 `a=A`(旧值)、
`b=[X]`(旧值),结果同样**原地写回** `X` 及 `A`。

### 4.3 `INPUT` / `OUTPUT`

- `INPUT`:`A := getchar()`,EOF 行为与底层 Malbolge20 解释器一致(参见
  `malbolge/malbolge20.py` 现有 EOF 处理,不是 `.mg` 层引入的新规则)。
- `OUTPUT`:`putchar(A)`,即输出 `A mod 256` 对应字节。
- 两者都**不改变** `A` 以外的任何内存(不像 `ROT`/`OPR` 会顺带修改一个变量),这也是
  `mg_d_repeat.mg` 示例里选择在循环体内只用 `OUTPUT` 而不是 `ROT` 的原因。

### 4.4 `IND_OPR X` —— 间接 crazy 运算(数组/指针访问)

**`A, [[X]] := crazy(A, [[X]])`**(2017 论文表 13,注意是**双重取址** `[[X]]`,不是
`[X]`)。与 `OPR X` 的本质区别:`OPR X` 操作的是变量 `X` 自己的存储单元(编译期固定地
址);`IND_OPR X` 把 `X` **当前存的值当成一个内存地址**,对那个地址上的内存做
crazy 运算。这是 `.mg` 语言里唯一能做到"运行期决定操作哪个内存单元"的指令,用来实现
数组/栈(2017 论文 §5–7,数组下标、`PUSH`/`POP` 递归栈都是拿 `IND_OPR` 手写出来的
语法糖,`.mg` 本身没有数组/栈的专门语法)。执行后控制流会跳到 `MAIN` 的入口再绕回来
(`PC := ENTRY@MAIN`,实现细节属于 LAL 后端,`.mg` 用户不需要关心,只需知道这是当前实
现里最"重"的一条指令)。

### 4.5 `FLAG` / `SET` / `RESET` / `FLIP` / `IF...ELSE...END`

- `FLAG name = TRUE|FALSE`:全局声明一个布尔标志,初值 `TRUE`→内部 `FLAG_ON`、
  `FALSE`→内部 `FLAG_OFF`。
- **flag 周期机制**:LAL 层的 `FLAG` 概念本身支持周期 `p ∈ {2,4,5,6,9}`(2016 论文
  表 1 备注),取值 `0..p-1`,`0` 表示 `ON`(active),其余表示 `OFF`;**每次该 flag
  被 `IF`/`NEXT` 检查(执行)一次,内部计数就 `+1 mod p`**。但 `.mg` 语法本身**只暴露
  布尔 `TRUE`/`FALSE` 声明**,编译器为 `.mg` 生成的所有 flag(用户声明的 + 内部管理用
  的 `FLAG_JMP`/`FLAG_CASE0..2`/`FLAG_REV_OPR_ROT` 等)一律是**周期 2**
  (`Program.cc` 全部用 `p=2` 建的 flag)。也就是说 `.mg` 层的 flag 永远是"纯二值",
  周期 4/5/6/9 是 LAL 层留给别的(非 `.mg`)用途的能力,`.mg` 编译器不会生成它们。
- `SET flag`:让 flag 变为 `ON`,不论进入前是什么状态。实现是一个自跳转 trick
  (2016 论文图 8):`Label: IF flag; BRANCH Label`。因为每次 `IF` 检查后 flag 自动
  `+1 mod 2`(即翻转),这个自环最多循环两次就必然以 `flag=ON` 状态跳出——`ON` 时
  跳自己(再检查一次,变 `OFF`);`OFF` 时才不跳,但这次检查完 flag 又翻回 `ON`,于是
  离开循环时状态恒为 `ON`。
- `RESET flag`:实现是 "`SET` 的同一段代码 + 末尾多一条 `NEXT flag`"(2016 论文 §5.3
  原文明确说明),即先用同一自环把 flag 收敛到 `ON`,再显式翻转一次变成 `OFF`。
- `FLIP flag`:直接翻译成单独一条 `NEXT flag`(`CodeBlock::flip`,`CodeBlock.cc:394`
  )——因为 `.mg` 的 flag 永远是周期 2,`NEXT`(计数 +1 mod 2)等价于"无条件翻转"。
  `FLIP` 不检查、不分支,只是切换状态,和 `SET`/`RESET`(收敛到确定状态)语义不同。
- `IF flag BLOCK1 ELSE BLOCK2 END`:`flag` 为 `ON` 时执行 `BLOCK1`,否则执行
  `BLOCK2`,执行完毕汇合到 `END` 之后。**`ELSE` 分支不可省略**(语法里没有"无 ELSE
  的 IF"产生式,只能 `ELSE` 后接空块)。

### 4.6 `REPEAT n BLOCK END` / `BREAK [n]`

- `REPEAT n`:`n` 是编译期常量(十进制或三进制字面量,**不能是变量或表达式**,
  `repeat_number` 产生式只接 `number` 或关键字 `INF`),循环体执行恰好 `n` 次。
  代码生成上**不是简单展开 n 份**,而是把 `n` 拆成二进制位,用 `O(log2 n)` 个"计数
  flag"实现一个基于"flag 每检查一次自动 +1"性质的二进制倒计数器
  (`CodeBlock::repeat`,`CodeBlock.cc:246-300`;原理见 2016 论文 §5.4),所以 `n`
  很大时代码体积不会线性爆炸,但循环体本身只会出现一份代码。
- `REPEAT INF`:无限循环,必须靠内部 `BREAK` 退出,否则程序永不到达 `REPEAT...END`
  之后的代码(会一直循环到程序被外部终止)。
- `BREAK` 等价于 `BREAK 1`,退出最近一层 `REPEAT`;`BREAK n` 退出最近的 `n` 层
  嵌套 `REPEAT`(`n` 同样是字面量常量,不可为变量)。`n` 若超过当前实际嵌套深度,报
  语义错误 `There is no 'REPEAT' to break`(**已实测**:`REPEAT 5 { BREAK 2 }`——只
  嵌套一层却 `BREAK 2`——精确复现此报错)。嵌套深度按**同一 `DEF...END` 例程内**的
  `REPEAT` 计数(`Routine::num_of_repeat_nested`),不会跨 `CALL` 传播。

### 4.7 `SWITCH X CASE0 ... CASE1 ... CASE2 ... END`

**按 `X` 的最低位 trit(个位,三进制末位)分支**:该 trit 为 0/1/2 分别执行
`CASE0`/`CASE1`/`CASE2` 对应的代码块(缺省的 CASE 视为空块)。

**前置约束(2016 论文表 5 原文"制約")**:`X` 除最低位以外的**所有** trit 必须为
`2`。也就是说,对 Malbolge20(20 trit)而言,`SWITCH` 执行前 `X` 的取值**只能是**下面
三者之一:

```
CON2 - 2 = 3486784398   (末位 trit = 0 → 走 CASE0)
CON2 - 1 = 3486784399   (末位 trit = 1 → 走 CASE1)
CON2     = 3486784400   (末位 trit = 2 → 走 CASE2)
```

这不是巧合:代码生成上,`SWITCH X` 直接 `JMP` 到 `X` 变量自己所在的内存地址
(`CodeBlock::switch_statement` 里的 `Instruction::JMP(var_label_inst)`,
`CodeBlock.cc:313`),依赖的是 Malbolge/低级汇编层"全 2 值紧邻的三个字面量,被当作指令
执行时经过 xlat2 变换后恰好三向跳转"这一固定单元技巧(与 `docs/hell-spec.zh.md` 3.1 节
`immutable_nops`/SNOP 的思路同源,都是利用"某几个特定字节值在 xlat2 表下有确定行为"
的性质)。**`.mg`/`ref/nagoya-ternary/parser` 完全不会静态检查这条约束**——`X` 存的
是别的值也能编译通过,只会在运行期产生"予測不能な動作"(2016 论文原话:不可预测的行
为,不是崩溃也不是报错,是走到未定义的分支/执行未定义的内存内容)。因此在 `.mg` 源码
里,通常的写法是先用 `ROT`/`OPR` 把 `X` 精确置成上面三个值之一,再紧跟着 `SWITCH X`。

**`CASE` 执行后 `X` 的值**:由于 `SWITCH` 是靠"跳进 `X` 所在内存地址并执行那里的(经
xlat2 变换后的)内容"实现的,该内存单元在 Malbolge 每条指令执行后都会被 xlat2
自我修改——也就是说 **`SWITCH` 执行完毕后,`X` 原来存的"全 2 值 + 末位"编码已被破坏,
不再是一个有意义的普通变量值**。`.mg` 语法层不阻止你在 `SWITCH X ... END` 之后继续对
同一个 `X` 做 `ROT`/`OPR`,但语义上应视为未定义,除非重新用 `ROT`/`OPR` 把它显式置回
一个已知值。

`SWITCH` 可以任意嵌套在 `REPEAT`/`IF` 内部,反之亦然(见五.2 实验)。

### 4.8 `DEF name ... END` / `PROTO name` / `CALL name` / `RETURN`

- 程序必须有且只有一个 `DEF MAIN`,它是程序入口(`Program::generate()` 无条件生成
  `PROGRAM_START_TO ENTRY@MAIN`)。**`.mg` 编译器不检查 `MAIN` 是否真的被定义**——
  漏写 `DEF MAIN` 依然能编译成功(exit code 0,无任何报错),只是生成的 `.mc` 里
  `ENTRY@MAIN` 是个悬空引用,后续 `.mc → .data` 汇编阶段大概率报错或产生垃圾(已实测:
  只有一个不含 MAIN 的 `DEF FOO` 时,`.mc` 顶部仍然写死 `PROGRAM_START_TO
  ENTRY@MAIN`,但整份输出里根本没有 `ROUTINE MAIN{` 块)。
- `PROTO name`:声明例程原型(允许在真正 `DEF` 之前被 `CALL`/`@name` 引用)。**所有
  `PROTO` 必须整体出现在所有 `DEF` 之前**(语法结构决定,见二)。
- **前向调用规则**:调用一个"物理上写在后面"的例程,必须先 `PROTO` 它,否则
  `Undefined routine` 语义错误(已实测)。调用一个"物理上写在前面"(已经 `DEF` 过)的
  例程不需要 `PROTO`(已实测)。
- ⚠ **`PROTO` 之后如果最终从未真正 `DEF`,不是编译错误而是 `parser` 直接崩溃
  (SIGSEGV,exit code 139)**——已实测复现(`PROTO FOO` + `CALL FOO`,但全程没有
  `DEF FOO`)。Python 后端必须自己做"每个 `PROTO` 都有对应 `DEF`"的静态检查,不能依赖
  参考实现的错误处理(它压根没做这个检查)。
- **函数无参数、无返回值**(2017 论文 §4.1 明确设计取舍):`CALL`/`RETURN` 之间不传
  递任何数据,要传数据只能靠全局变量或 `变量@例程名` 手动读写。
- **递归不安全**:`RETURN` 的实现是把"调用点之后的地址"存进该例程专属的**唯一一个**
  `RETURN_ADDR` 变量,再用 `DJMP`(动态跳转)读它跳回去(2017 论文 §4)。语法层完全不
  阻止一个例程调用自己或调用链形成环(已实测:`DEF SUB { CALL SUB; RETURN }` 编译
  通过,无警告),但由于 `RETURN_ADDR` 只有一份存储,**重入(递归/环路)会在返回前就
  被内层调用覆盖掉外层的返回地址**,导致返回到错误位置。2017 论文专门为此在更高层
  (C 子集编译器,不是 `.mg` 本身)引入了基于 `IND_OPR` 手写的栈(`PUSH`/`POP`,论文
  图 17)来支持真正的递归——`.mg` 语言本身没有内建递归支持,写递归需要自己实现调用栈。
- **`MAIN` 里的 `RETURN` 是"结束程序",不是"返回调用者"**:`CodeBlock::func_return`
  (`CodeBlock.cc:385-392`)特判了 `routine->name == MAIN_ROUTINE` 的情况——只有在
  非 `MAIN` 例程里,`RETURN` 才编译成 `DJMP` 跳回调用点;**在 `MAIN` 自己的例程体内
  写 `RETURN`,编译成的是无条件 `END`(终止整个程序)**,这与 C 语言 `return` from
  `main()` 的直觉一致,但意味着不能把 `MAIN` 当一个可以被 `CALL` 并正常"返回"的普通
  例程使用。
- **例程体如果没有显式 `RETURN` 就"跑到底",不是安全的隐式返回,而是会终止整个程序**:
  每个 `DEF...END` 结束时,`Routine::end()`(`Routine.cc:248-252`)总会在该例程主代码
  块末尾追加一条无条件 `END` 指令。若该例程以显式 `RETURN` 结尾,这条自动追加的 `END`
  是不可达死代码(已用 `test/fixtures/nagoya/mg_e_call.mg` 的编译产物验证);但**若
  该例程没有以 `RETURN` 收尾就直接落到 `END`**,这条自动追加的 `END` 就会被真正执行到
  ——**导致整个程序在这里终止,而不是返回给调用者**(已实测复现:`DEF SUB {OUTPUT}`
  被 `CALL` 后,`SUB` 末尾生成的 `LABEL1: END` 确实是可达代码)。因此**除 `MAIN`
  外的每个例程,必须以显式 `RETURN` 结尾**,这是一条不会被语法检查、但违反会导致运行
  期"程序莫名其妙提前退出"的强约束。

---

## 五、嵌套规则(实验验证)

用 `ref/nagoya-ternary/parser -s 1 <file.mg>` 直接编译到 `.mc`,检查是否报语法/
语义错误(不必跑完整 `.mg → .mb` 管线),验证了以下几点:

1. **`REPEAT`/`IF`/`SWITCH`/嵌套 `REPEAT` 可以任意互相嵌套**,包括 4 层深
   (`REPEAT { IF { REPEAT { SWITCH { CASE1: REPEAT {...} END } END } END } END }`)
   —— 编译无错误、生成 185 行 `.mc`。
2. `BREAK n` 可以跨越正确数量的嵌套层退出(`REPEAT 5 { REPEAT 5 { BREAK 2 } }` 无
   错误);超出实际嵌套深度会报 `There is no 'REPEAT' to break`。
3. `VAR` 声明顺序:一个例程内必须先声明完全部 `VAR` 再写语句,否则 `syntax error`。
4. `FLAG` 只能在全局(顶层)声明,写在 `DEF...END` 内部是 `syntax error`。
5. `CALL` 只能引用已经 `DEF` 过的例程,或已 `PROTO` 声明过的例程;两者都没有则
   `Undefined routine` 语义错误。
6. `变量@例程名` 允许引用一个**尚未定义**、但已 `PROTO` 的目标例程里、当时**尚未
   声明**的变量(占位后延迟检查),已实测通过。
7. 例程末尾缺失 `RETURN`(`MAIN` 除外)会让程序在此处真正终止而非返回调用者(见 4.8)。
8. `PROTO` 声明后从未 `DEF` 会导致解析器 SIGSEGV,而非报错退出。
9. **十进制字面量不允许前导零**(`007` → `syntax error`);三进制字面量不校验每位
   是否 ≤ 2(`39t` 静默算出 `18`)。
10. **重要工程事实**:无论报的是语法错误还是语义错误(`Undefined variable`、
    `Undefined routine`、`Variable ... already defined`、`There is no 'REPEAT' to
    break`、`Undefined flag` 等),`ref/nagoya-ternary/parser` 的**进程退出码永远是
    0**——错误只打印到 stderr,`main.cc` 从不检查 `parser.parse()` 的返回值。
    `scripts/mg2mb.sh` 目前的 `set -euo pipefail` **捕获不到**这类错误(退出码是 0),
    如果上游 `.mg` 有语义错误,脚本会静默地把空的/半截的 `.mc` 传给下一阶段。**Python
    版编译器如果要复用"检查 stderr 文本"这种脆弱方式,不如直接抛异常**;这既是给未来
    `scripts/mg2mb.sh` 使用者的提醒,也是 Python 后端设计 API 时应该规避的反面教材。

---

## 六、已知边界(来自项目已确认事实 + 本次核实)

- `GOTO` 是 scanner/parser 都声明的 token(`scanner.ll:36`、`parser.yy:25`),但
  `parser.yy` 里**没有任何产生式使用它**——纯保留字,当前版本完全不可用,写
  `GOTO` 会直接 `syntax error`(它甚至没有被消费成一个可规约的非终结符)。
- 函数(`DEF`)无参数、无返回值(见 4.8)。
- 数值理论上应非负、`≤ 3^20-1`(Malbolge20 一字长上界),但**编译器不做任何范围/符号
  校验**,越界或负数记法(负数本来就没有字面量语法)完全是使用者自己的责任。
- `.mg` 只有一种"跨模块"机制——`变量@例程名`,没有 `import`/命名空间/文件包含语法;
  一个 `.mg` 源文件即整个程序。

---

## 七、每个特性的最小示例

以下五个是仓库里现成、已通过完整 `.mg→.mc→.mb` 管线验证并与参考 C 解释器比对过
输出的示例(`test/fixtures/nagoya/README.md` 有详细交叉验证记录),覆盖了
`OUTPUT`/`VAR`+`ROT`/`INPUT`/`REPEAT`+`BREAK`/`CALL`+`RETURN`:

| 特性 | 文件 |
|---|---|
| 最小 `OUTPUT` | `test/fixtures/nagoya/mg_a_minimal.mg` |
| `VAR` + `ROT` + `OUTPUT` | `test/fixtures/nagoya/mg_b_hi.mg` |
| `INPUT` + `OUTPUT` | `test/fixtures/nagoya/mg_c_echo.mg` |
| `REPEAT n` / `REPEAT INF` + `BREAK` | `test/fixtures/nagoya/mg_d_repeat.mg` |
| `PROTO` + `CALL` + `RETURN` | `test/fixtures/nagoya/mg_e_call.mg` |

以下补充覆盖 `IF`/`SWITCH`/`FLAG`/`IND_OPR`/嵌套(未编译进仓库 fixture,仅用于说明
语法,已用 `ref/nagoya-ternary/parser` 验证可编译):

```
# IF / ELSE / SET / RESET / FLIP
FLAG F = TRUE
DEF MAIN
  IF F
    OUTPUT
  ELSE
    INPUT
  END
  RESET F
  FLIP F        # F 现在又变回 ON
END
```

```
# SWITCH:X 必须先被置成 CON2-2/CON2-1/CON2 三者之一
VAR X = 3486784399   # = CON2 - 1, 三进制末位为 1
DEF MAIN
  SWITCH X
  CASE0
    OUTPUT
  CASE1
    INPUT
    OUTPUT
  CASE2
    OUTPUT
    OUTPUT
  END
END
```

```
# IND_OPR:把变量的“值”当地址间接操作(数组/栈的基础)
VAR PTR = 0     # 运行期会被赋成某个真实地址
DEF MAIN
  IND_OPR PTR   # A, [[PTR]] := crazy(A, [[PTR]])
END
```

```
# 嵌套:REPEAT 里套 IF 里套 REPEAT 里套 SWITCH(已实测可编译)
VAR X = 300
FLAG F = TRUE
DEF MAIN
  REPEAT 2
    IF F
      REPEAT 3
        SWITCH X
        CASE0
          OUTPUT
        CASE1
          REPEAT 2
            OUTPUT
          END
        CASE2
          OUTPUT
        END
      END
    ELSE
      OUTPUT
    END
  END
END
```

---

## 八、Python 编译器后端需要注意的坑

1. **`END` 是唯一的块结束关键字**,不要照抄论文表格里的 `IFEND`/`REPEATEND`/
   `SWITCHEND` 记法去设计词法表——那只是论文的助记写法,真实语法里根本不存在这三个
   token(见二)。
2. **三进制字面量 `NNNt` 不能直接照抄参考实现的宽松解析**:参考实现允许任意 `0-9`
   数字字符并按 `sm=sm*3+digit` 硬算,不做每位 ≤2 的校验;Python 实现应该在词法/语法
   层显式拒绝非 0/1/2 的位,而不是复刻这个已知的实现漏洞。
3. **十进制字面量禁止前导零**(单独的 `0` 除外),`Python` 实现要在词法层就拒绝
   `0123` 这种写法,而不是等到后面数值转换时才发现问题。
4. **没有数值范围/符号校验**是参考实现的已知缺陷,不建议照搬;Python 后端应主动校验
   `VAR`/`REPEAT n`/`BREAK n` 等字面量落在 `[0, 3^20-1]`(或对应变体的字宽上界)内。
5. **`SWITCH` 的"除末位外全为 2"约束是纯运行期契约,参考实现完全不做静态检查**——
   Python 后端如果想比参考实现更安全,可以选择:(a) 保持现状不检查(兼容行为),或
   (b) 静态分析"`SWITCH X` 前最近一次对 `X` 的写入是否明显来自 `CON2±{0,1,2}`"做尽力
   而为的告警,但不能保证完备(值可能来自 `INPUT`/`IND_OPR` 等运行期来源)。
6. **递归 `CALL` 不会被参考实现拒绝,但语义上是错的**(见 4.8);如果 Python 后端的目
   标是给"未来的 Python→.mg 编译器"当后端,而那个更高层编译器可能生成递归调用,就必须
   现在决定:是在 `.mg` 层直接拒绝递归调用图(静态检测 `CALL` 图里的环并报错,比参考
   实现更严格),还是在生成 `CALL`/`RETURN` 代码时就自动引入 2017 论文 §7 那种基于
   `IND_OPR` 的显式栈。二者选一,不要悄悄放过递归又不处理。
7. **非 `MAIN` 例程必须以显式 `RETURN` 收尾**,否则会在该例程被调用时把整个程序提前
   终止掉(见 4.8 第 6 条)。这是一个参考实现允许你犯、但后果是"程序莫名其妙提前退出"
   的陷阱,Python 后端至少应该给出编译期警告(理想情况下报错)。
8. **`PROTO` 后必须有匹配的 `DEF`**,否则参考实现直接段错误;Python 实现必须做这项
   静态检查并给出清晰错误信息,而不是让最终用户遭遇底层崩溃。
9. **`DEF MAIN` 缺失不是错误,是静默生成悬空引用** ——Python 后端应该主动检查"程序里
   有且仅有一个 `DEF MAIN`"并在缺失/重复时明确报错。
10. **不要依赖参考实现的进程退出码判断成败**——它对所有语法/语义错误都返回 0,唯一可
    靠的信号是 stderr 是否非空,或者(更好)Python 后端自己实现的编译器直接用异常
    传递错误,不要模仿这种"永远 exit 0"的行为。
11. **`FLAG` 只能全局声明、`VAR` 必须先声明后语句**,两者都是纯语法限制,Python 语法
    树/解析器要把这两条当成硬性产生式约束,而不是留到语义检查阶段才处理。
12. **变量作用域是"当前例程 → 全局"两层查找 + 显式 `@例程名` 跨例程引用**,没有更复杂
    的嵌套作用域;局部变量遮蔽同名全局变量。Python 后端的符号表设计只需要这两层
    (当前例程 dict + 全局 dict)加一个"其他例程" 的按名字查表(用于 `@`),不需要更
    通用的作用域链。
13. `ref/nagoya-ternary/parser` 的输出(`.mc` 的具体分支/flag 命名、`-m`/`-d`/
    `-c`/`-i` 风格选择、随机种子)是**非规范性的实现细节**,不同 `-s` 种子/风格标志会
    产出功能等价但字节不同的 `.mc`;`.mg` 语言规格本身(本文档范围)与这些代码生成细
    节无关,未来 Python 后端完全可以采用自己的、更简单/确定性的代码生成策略,只要保持
    `.mg` 语言语义等价即可,不需要位对位复刻参考实现的生成风格。

---

## 九、存疑点

- **`IND_OPR` 的具体运行期机制**(表 13 的 `PC := ENTRY@MAIN` 那部分,即执行后如何
  跳回原程序位置)依赖 2017 论文 §5–6 描述的、只在 `ref/nagoya-lowass`(LAL→Malbolge20
  汇编器)层实现的"固定单元 + 数据模块固定值"技巧,本文档只核实了 `.mg` 层可见的输入
  /输出语义(`A,[[X]]:=crazy(A,[[X]])`),没有去逐行核对 `ref/nagoya-lowass` 里
  `IND_OPR` 单元的具体字节布局——如果 Python 后端要自己重新实现 `IND_OPR` 的代码生成
  (而不是照搬这套固定单元技巧),需要额外单独研究 `ref/nagoya-lowass` 源码或
  2017 论文图 14/表 15。
- **`REPEAT n` 的二进制倒计数器代码生成细节**(哪个 flag 对应哪一位、`SET`/`RESET`
  的初始化顺序)本文档只做了高层次描述并给出了论文出处(2016 论文 §5.4),没有逐行
  验证生成的 `.mc` 是否与该算法描述完全一致——这是 LAL 后端代码生成的实现细节,不影响
  `.mg` 语言本身的语义(REPEAT n 精确执行 n 次是已用 `mg_d_repeat` fixture 端到端验证
  过的行为),仅在"要不要照搬这个具体优化"这个问题上留有余地。
- **数值上界 `3^20-1` 是否在其他 Nagoya 工具(`ref/nagoya-lowass`)里有隐式校验**未
  核实——本文档只确认了 `ref/nagoya-ternary`(.mg→.mc 这一步)没有校验,不代表后续
  管线阶段完全没有任何界限检查(但从 `scripts/mg2mb.sh` 的注释看,`.data→.mb` 阶段
  `init` 工具对越界情况的行为也未见文档化)。
- **`variable_str AT IDENT` 里目标例程若从未定义任何 routine(既没 `PROTO` 也没
  `DEF`)时的具体报错文本**未逐一测完所有排列组合,只验证了"目标例程完全不存在" →
  `Undefined routine`(通过 `call_statement` 路径验证,`variable ... AT IDENT` 路径
  报错文本推断应一致,均查 `program->routines`,但未对 `变量@不存在的例程` 这一具体
  组合单独跑一次实验确认报错文本)。

---

## 参考

- `ref/nagoya-ternary/scanner.ll`、`parser.yy`、`CodeBlock.cc`、`Routine.cc`、
  `Program.cc`、`Variable.cc`、`Radix.cc`、`Option.cc`、`main.cc`、`define.h`
- `ref/nagoya-ternary/README.en.md`
- 河邉翔平・酒井正彦・西田直樹・関浩之,"難読性の高い Malbolge コードを生成する
  コンパイラのための中間言語", 電子情報通信学会技術報告, Vol.116, No.127,
  SS2016-12, pp.105-110 (2016).
- 坂梨元軌・河邉翔平・酒井正彦・西田直樹・橋本健二,"再帰呼び出しを持つ C 言語
  サブセットから Malbolge へのコンパイラ", 電子情報通信学会技術報告, Vol.117,
  No.136, SS2017-18, pp.145-150 (2017).
- `test/fixtures/nagoya/README.md`、`test/fixtures/nagoya/mg_*.mg`
- `docs/hell-spec.zh.md`(姊妹文档:HeLL/LMAO 语言规格,SWITCH 的固定单元跳转技巧与其
  3.1 节 `immutable_nops` 思路同源)
