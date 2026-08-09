# HeLL 语言规格(基于 LMAO v0.6.0 逆向整理)

> [English](hell-spec.md) | **中文**

> 本文档依据 `ref/LMAO/src/lmao.l`、`lmao.y`、`label.c`、`prefix.c`、`xlat.c`、
> `layout.c`、`initialize.c`、`malbolge.h/.c` 及 LMAO README 逐行核对整理,
> 并与 `test/fixtures/hell/` 六个示例逐条对照。
> 作为 pyMalbolge 的 Python 版 HeLL 汇编器的实现依据。
> 整理日期:2026-07-20;LMAO 版本:v0.6.0(commit 3ea747e)。

---

## 一、词法(来自 `lmao.l`)

### 1.1 空白与注释

- 空白:`[ \t\r]`,以及裸换行 `\n`;两者都会把内部标志 `require_whitespace` 清零(见 1.4)。
- 注释(会被整段丢弃,不产生 token):
  - 行注释:`;`、`%`、`#`、`//` 开头到行尾;
  - 块注释:`/*...*/`,允许块内出现单独的 `*` 或 `/`,只要不是紧邻的 `*/` 就不会提前结束。

### 1.2 块分隔(EMPTYLINE 的三种来源)

- **空行**:"换行—可选空白—再换行"。连续空行只产生一个 `EMPTYLINE`,且只有在**不处于花括号内**时才产生;花括号内的空行被静默丢弃。
- **`{`**:置位 suppress 标志并返回 `EMPTYLINE`;花括号已打开时再遇 `{` 报错。
- **`}`**:清除 suppress 标志并返回 `EMPTYLINE`;无对应 `{` 时报错。
- **关键事实**:`{`、`}`、空行三者在语法层面都归约成**同一个 EMPTYLINE token**,花括号只是空行的"显式拼写"。`}{` 连写 = 结束上一块并立即开启下一块(等价于中间一个空行)。
- 文件末尾若仍在花括号内(未闭合)是致命错误。

### 1.3 段头 `.CODE` / `.DATA`

- 段头不能出现在 `{ }` 块内部(报错)。
- `.DATA` 置位 `in_data_section` 标志,`.CODE` 清零。该标志决定 `/` 的词法归属(见 1.7)。

### 1.4 标识符类 token 与"必须有分隔符"规则

- `identifier = [A-Za-z_][0-9A-Za-z_]{0,99}`(最长 100 字符);`label = identifier ':'`。
- `U_{identifier}` → U_ 前缀 token(值为去前缀后的名字);`R_{identifier}` 同理。
- **禁止把 Malbolge 命令关键字、`U_...`、`R_...` 用作标签名**(词法级报错)。但 `U_x`、`R_x` 作为普通标识符(非标签定义)允许,专用于 `.DATA` 表达式里的前缀引用。
- **`require_whitespace` 机制**:字符串、字符字面量、数值常量、`C0/C1/C2/C20/C21/EOF`、`RNop`、命令助记符、前缀标识符、普通标识符这些"类单词"token 匹配成功后置位标志;下一个 token 若同样是"类单词"token 则报错 "Misformed identifier"。即 **`42abc`、`'a'C1`、`InOut` 这类紧贴写法非法**,必须用空白或标点隔开。逗号、花括号、运算符、空白、换行清零该标志;`(` `)` 不清零。

### 1.5 数值字面量

| 语法 | 值 | 备注 |
|---|---|---|
| `0*[0-9]{1,5}` | 十进制,允许前导 0 | > 59048 报错 "Integer too big" |
| `0t[0-2]{1,10}` | 三进制,最左位最高 | 位数上限 10,天然 ≤ 59048;六个示例中未实际使用 |
| `'c'` | 单字符 ASCII 值 | 裸字符排除 `'` 与 `\`;转义仅 `\' \n \r \t \\`(**无 `\0`**,`'\0'` 会得到字符 `'0'` 的值) |
| `C0/C1/C2/C20/C21/EOF` | 0 / 29524 / 59048 / 59046 / 59047 / 59048 | `EOF` 是 `C2` 同义词 |

### 1.6 字符串字面量

双引号包裹,允许反斜杠转义,不允许裸换行/未转义引号。转义解码在语法动作层(见 3.2),支持 `\n \r \t \\ \0`(**字符串支持 `\0`**,与字符字面量不同)。

### 1.7 特殊符号

| 符号 | 语义 |
|---|---|
| `,` | 仅用于 `STRING , Dataexpression`(字符串字符间分隔符) |
| `{` `}` | 均产生 EMPTYLINE(见 1.2) |
| `.OFFSET` / `@` | 等价;`@` 不需要空白分隔 |
| `?` | DONTCARE:占用地址但值不保证 |
| `?-` | NOTUSED:完全不占地址 |
| `+ - * / >> << !` | 运算符;**`/` 上下文相关**:`.DATA` 段是除法,`.CODE` 段是 xlat2 循环分隔符 |
| `( )` | 分组 |

其余字符 → 词法报错。

---

## 二、语法(近似 EBNF,依据 `lmao.y`)

```ebnf
Start            ::= EMPTYLINE* Program
Program          ::= ( Code | Data )*
Code             ::= ".CODE" Codeblocks
Data             ::= ".DATA" Datablocks

Codeblocks       ::= Codeblock ( EMPTYLINE Codeblock )*
Datablocks       ::= Datablock ( EMPTYLINE Datablock )*

Offset           ::= ( ".OFFSET" | "@" ) CONSTANT EMPTYLINE*

Codeblock        ::= ε | Offset? LABEL Codeexpressions
Datablock        ::= ε | Offset? LABEL Dataexpressions

Codeexpressions  ::= ( LABEL | Codeexpression )*
Codeexpression   ::= "RNop" | XlatCycle
XlatCycle        ::= COMMAND ( "/" COMMAND )*
                     /* COMMAND ∈ {MovD,Nop,Jmp,In,Out,Opr,Rot,Hlt} */

Dataexpressions  ::= ( LABEL | Dataexpression
                     | STRING | STRING "," Dataexpression )*

Dataexpression   ::= Dataexpression (">>"|"<<") Crazied   /* 左结合,优先级最低 */
                    | Crazied | "?" | "?-"
Crazied          ::= Crazied "!" Sum | Sum                 /* 左结合 */
Sum              ::= Sum ("+"|"-") Product | Product       /* 左结合 */
Product          ::= Product ("*"|"/") Dataatom
                    | Product ("*"|"/") "(" Dataexpression ")"
                    | Dataatom | "(" Dataexpression ")"
Dataatom         ::= CONSTANT | IDENTIFIER
                    | R_PREFIXED_IDENTIFIER
                    | U_PREFIXED_IDENTIFIER IDENTIFIER     /* U_TARGET ANCHOR */
```

**运算符优先级**(从低到高,与常见直觉不同):`>> <<` < `!` < `+ -` < `* /`。

**每个 Dataexpression / Codeexpression(以及字符串展开的每个字符)恰好对应一个连续内存单元**——块内空白分隔的多个表达式依次填入相邻地址。

**多标签可共享同一单元**(标签别名):`LABEL` 可在表达式序列中反复出现。

**空块归约为空并被丢弃**,因此 `}{` 连写合法。

---

## 三、语义

### 3.1 `.CODE` 段:xlat2 循环与 8 条命令

| 助记符 | 操作码 | 语义 |
|---|---|---|
| Nop | 68 | 无操作(所有不落在其余 7 个操作码上的值都是 Nop) |
| MovD | 40 | `D = [D]`;C、D 自增 |
| Opr | 62 | `A,[D] = crazy(A,[D])`;C、D 自增 |
| Jmp | 4 | `C = [D]`;仅 D 自增 |
| Rot | 39 | `A,[D] = rotate_right([D])`;C、D 自增 |
| Out | 5 | 输出 `A mod 256`;C、D 自增 |
| In | 23 | 读一字符到 A;EOF 时 `A = C2`;C、D 自增 |
| Hlt | 81 | 终止 |

- **单命令**(如 `Jmp`):仅首次执行保证是该操作码,执行后的自修改结果不做约束,可放在任意合法地址。
- **xlat2 循环 `Cmd1/.../CmdN`**:该单元连续执行 N 次依次表现出的操作码,循环闭合。合法性静态验证(`xlat.c: is_xlatcycle_existent`):对候选起始字符反复套用 XLAT2 表推导,非 Nop 操作码必须精确匹配,Nop 位置只需"是 Nop"。某些循环组合数学上不存在 → 报错。
- **`RNop`**:自环 Nop 的语法糖。每个地址 mod 94 都存在至少一个"永远是 Nop"的字符(`xlat.c` 硬编码 94 字符 `immutable_nops` 表),因此 `RNop` 在任意地址都能放置。
- **位置约束**:起始字符须为可打印 ASCII(33–126)且 `(地址 mod 94 + 字符值) mod 94` ∈ 8 操作码集合。由布局阶段求解。

### 3.2 `.DATA` 段:表达式求值(`initialize.c`)

- 算术在 **mod 59049** 下进行;负值(减法)回绕至非负。注意 C 源码里用 `%= C2`(59048)而非 `%= 59049` 做溢出削减,仅 `+`/`*` 可能触发——移植时需逐行对照该边界行为。
- **`/` 是整数除法**;除零在 LMAO 中未检查(UB),Python 实现应显式报错。
- **`>> <<` 是三进制旋转**(非移位):`>> n` = 右旋 n 位,`<< n` = 右旋 `10-n` 位,由单步 `rotate_right` 复合。**n ≥ 10 时取模 + 警告,不报错**(README 说 0≤n<10,以源码行为为准)。
- **`!` 是 crazy 运算**(与 `malbolge/core.py` 的 `crazy()` 同表)。
- **标签引用求值**:
  - 普通 `LABEL`:目标地址经"减 1、结果为 0 回绕成 C2"调整(适配 Jmp 后 C 自增/MovD 后 D 自增的语义)。
  - `R_LABEL`:净效果为目标地址本身(不减 1)。约束:目标必须是 `.CODE` 标签,且不能是所在代码块最后一格。
  - `U_TARGET ANCHOR`:在**同一连续数据块**内从当前格向后找 `ANCHOR`(DATA 标签)得负偏移;`TARGET`(CODE 标签)前须有等量 Nop 前缀链——已有单元必须全是 Nop,若 `TARGET` 是块首则自动合成 RNop 补足;否则报错。
- **`?`**:占地址,不生成初始化,值不保证。
- **`?-`**:不占地址;**标签不得指向 `?-`**(LMAO 仅警告 + 未定义行为;Python 实现应直接报错)。
- **字符串展开**:`"abc"` → `'a' 'b' 'c'` 三个单元;`"abc", SEP` → `'a' SEP 'b' SEP 'c'`(字符间插入,`2n-1` 个单元)。

### 3.3 `ENTRY` 标签

`.DATA` 段必须定义 `ENTRY` 标签,否则报错。程序启动时 D 指向 `ENTRY` 单元,C 指向一条 Jmp,A 初值未定义。`ENTRY` 定义在 `.CODE` 段无效(会被当作找不到入口)。

### 3.4 `.OFFSET` / `@`

把块首单元固定到绝对地址(`[0, C2]`,越界报错)。`.CODE` 块会在目标地址前一格额外预留一个占位(`.DATA` 块无此预留,两者不对称)。`Offset` 与其后的 `LABEL` 之间允许空行(不拆块)。

### 3.5 非法程序判定(错误来源汇总)

1. **词法级**:缺分隔符("Misformed identifier")、整数越界、非法标签名、花括号不匹配、段头出现在花括号内、未知字符。
2. **语法级**:LALR 语法错误。
3. **语义级**:标签重定义;孤立标签(后无数据/代码字);未定义标签引用;`R_` 用于块尾;`U_` 的 ANCHOR 不在同一数据块 / Nop 链构造失败;缺 `ENTRY`;xlat2 循环不可实现;`.OFFSET` 越界或冲突;布局无解(地址空间放不下)。

---

## 四、示例特性对照表(六个 fixture)

| 特性 | 出现位置(文件:行) |
|---|---|
| 两段以上 `.DATA`/`.CODE` | hello_world(35/136;32/43 起) |
| `{ }` / `}{` 连写 | simple_cat:38-57;cat_halt_on_eof:205/221/236/250/268 等 |
| 行注释 `;` | hello_world:214;digital_root:442-443 |
| 多别名标签 | hello_world:312;adder:100-101 |
| 全部 8 助记符 | cat_halt_on_eof、digital_root |
| 5-循环 / 9-循环 | hello_world:73;hello_world:110/114 |
| `RNop` | hello_world:111-112/126-129;cat_halt_on_eof:126-127;digital_root:197-198;adder:80-81 |
| `.OFFSET` 关键字 | cat_halt_on_eof:124 |
| `@` 简写 | hello_world:121;digital_root:196;adder:79 |
| 裸十进制常量 | cat_halt_on_eof:434(唯一) |
| `0t` 三进制 | 无实际使用 |
| 字符字面量 | simple_hello_world:67-83;digital_root:456/512 |
| 字符串 + 分隔符 | hello_world:40(唯一) |
| `!` crazy | simple_hello_world:68/73 |
| `<< >>` | simple_hello_world:70/76/78/80;digital_root:456/512;adder:719/981/1075/1078 |
| `+ - *` | 六个示例均未使用(仅 README) |
| 括号 | digital_root:456 |
| `U_` 前缀 | hello_world:147/149/151;cat_halt_on_eof:139/146/148/158/164/168-170;digital_root:211/213/247/252-253/271;adder 多处 |
| `R_` 前缀 | 全部示例大量使用(adder 214 处) |
| `?` | cat_halt_on_eof:141/150/160/167 |
| `?-` | simple_cat:48/52;hello_world:69 等;digital_root:510/513;adder:412/719/1061 |
| `ENTRY` | 六个文件各一处 |

---

## 五、Python 实现注意事项

1. `/` 的词法含义随当前段切换,词法器需带段状态。
2. `require_whitespace` 分隔规则必须实现,否则与 LMAO 行为不一致。
3. 运算符优先级 `>> <<` < `!` < `+ -` < `* /`,与直觉相反,勿凭常识排序。
4. `R_`/`U_` 前缀:不能作标签名,可作表达式引用——定义位置与引用位置两套规则。
5. `{ }` 与空行统一为同一"块结束"事件处理。
6. 标签"减一/回绕"、`R_` 不减一、`U_` 的块内向后找 ANCHOR + RNop 链校验/合成,是最易出 bug 的部分,须对照 `prefix.c`/`initialize.c` 原文逐行复刻。
7. 旋转量越界是"取模 + 警告"而非报错(以源码为准)。
8. 标签指向 `?-`:LMAO 仅警告(未定义行为),Python 实现改为直接报错(比原版更严格)。
