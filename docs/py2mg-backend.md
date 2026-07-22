# py→.mg 直连后端(py2mg)设计文档

> 模块:`malbolge/compiler/py2mg.py`,公开 `compile_python_to_mg(source) -> str`。
> 接入:`compile_python_to_mb(py, backend="direct")`、CLI `--backend=direct`。
> 整理日期:2026-07-21。本文档描述 **v0**(严格对齐 py2c v1 的语言子集,不新增语言特性)。

## 1. 动机

现有管线是两步:Python --`py2c`--> 名古屋 C 子集 --`c2mg`--> `.mg`。C 层是为了复用名古屋
参考编译器,但它强加了一批**只为绕过 C 子集缺陷**而存在的开销(见 `docs/findings.md`):

- **三地址展开**:C 子集无运算符优先级历史包袱 + 上游 bool 类型损坏,py2c 把每个表达式拆成
  三地址式并物化 bool 为 int 0/1,产生大量中间局部变量与拷贝。
- **"每个函数都按递归处理"**:`c2mg` 忠实复刻参考实现,把 `is_recursive` 硬编码为 `True`
  (`check_recursive_call` 算出真实可达性后又丢弃),于是**每个**函数——包括叶子函数、
  注入的 `zzmul/zzdiv/zzmod`、以及 `main`——都要付全量 push/pop 栈保护。
- **共享全局 temp 池 → 双递归 bug(A2)**:`get_temporary_variable` 一律插进全局变量表
  (一个共享 FIFO free-list),而 push/pop 保护**排除** temporary,于是一个表达式里跨两次
  兄弟递归调用、暂存在 temp 里的中间结果会被内层调用覆盖。

直连后端跳过 C 层,从 Python AST 直接发射 `.mg`,在**复用 c2mg 全部经验证的代码生成原语**
(算术 `add/sub`、比较 `lt/eq/not_`、`inc/dec`、逻辑 `and/or`、栈 `push_stack/pop_stack`、
`SWITCH` 型 `if/while`、调用 ABI)的前提下,只改**帧策略**。因为算术/比较/调用序列逐字节
复用 c2mg,直连产物与 C 路径**计算结果一致**;体积差异只来自帧策略与去除 C 层冗余。

## 2. 复用与差异总览

| 方面 | C 路径(py2c + c2mg) | 直连(py2mg) |
|---|---|---|
| 前端 | Python→C(AST→C 文本),再 C→.mg(重新词法/语法分析) | Python AST 直接→.mg |
| 算术/比较/逻辑/调用 ABI 原语 | c2mg 实现 | **原样复用 c2mg 的方法** |
| 三地址展开 | 恒做 | 不做(表达式自然嵌套求值) |
| bool 物化为 int | 恒做(控制流物化 0/1) | 仅**值上下文**才物化;`if/while` 条件直接喂 `SWITCH` |
| temp 归属 | 全局共享池,声明为全局 `VAR` | **每函数私有**,声明在该函数 `DEF` 内 |
| 递归判定 | 硬编码全 `True` | **真实环检测**,仅环内函数为递归 |
| 帧保护范围 | 每函数的非静态非 temp 局部 | 仅递归函数:非静态局部 **+ 跨调用存活的 temp** |
| 乘除模 helper | py2c 注入为 C 函数,c2mg 编译 | 以同款 Python 子集**懒注入**为 `.mg` 例程(仅真正用到才注入) |

## 3. 帧布局与调用 ABI

沿用 c2mg 的调用协定(已被 36/36 逐字节 + e2e 验证),因此调用/返回/递归栈机制与 C 路径同构:

- **无参无返回值的 `.mg` 例程**,数据经全局槽传递:调用方把第 i 个实参 `copy` 进
  `ARG{i}@被调例程`,`CALL` 之,再把 `RETURN_VALUE@被调例程` `copy` 进一个 temp 作为结果。
- 被调例程入口把 `ARG{i}`(静态槽)`copy` 进形参局部;`return e` 把 `e` `copy` 进本例程的
  `RETURN_VALUE`(静态槽)再 `RETURN`。
- **`RETURN_ADDR` 单槽 + 递归栈**:`.mg` 的 `RETURN` 只有一个 `RETURN_ADDR` 槽,重入会覆盖。
  对**递归被调**,`CALL` 点前后用 `push_stack/pop_stack` 保存/恢复 `RETURN_ADDR@被调`
  (这是 2017 论文机制,c2mg 的 `Block.generate` CALL 处理已按 `f.is_recursive` 条件发射,
  直连原样复用)。**非递归被调不产生任何 `RETURN_ADDR` 保存**——这是相对 C 路径的一处直接节省。

### 3.1 每函数 temp(关键结构改动)

直连把 temporary 声明为**其所属 `DEF` 内的局部 `VAR`**(`TMP0`、`TMP1`……),而非全局。
已实测确认 `mg2mc` 对不同例程的同名局部 `VAR` **按例程独立分配地址**(两个例程各写
`VAR a=…`,运行期是两个不同单元)。因此:

- **非递归的跨函数调用天然安全**:调用链上若无环,栈上同时出现的都是**不同**函数,它们的
  temp 占用**不同**地址,互不覆盖——**无需任何帧保护**。这正是"仅对递归函数上保护"的严格依据。
- c2mg 因 temp 全局共享,任何跨函数调用理论上都可能覆盖,故被迫全量保护;直连的每函数 temp
  从**机理上**移除了这一前提。

### 3.2 递归判定与保护范围

`check_recursive_call` 重写为**真实可达性**:一个函数是递归当且仅当它在调用图里能到达自身
(自递归或互递归成环)。仅这些函数在入口/出口发射 push/pop,保护集合为:

```
protect(F) = { F 的非静态、非 temp 局部 } ∪ { 在 F 的某个 CALL 点存活的 temp }
```

"跨调用存活的 temp"由**精确活性跟踪**得到:降低表达式时维护一个 `_live` 栈,凡在求值某个
可能含 `CALL` 的子表达式期间被持有的 temp,都记入被调所在函数的 `_cross_call_temps`。于是
`fib(n-1)+fib(n-2)` 里持有 `fib(n-1)` 结果的 temp 会在第二次 `CALL` 点被登记为跨调用存活 →
被纳入 `FIB` 的入口/出口保护 → 内层递归在自己的入口把该单元一并 push(保存外层活动记录的值)、
出口 pop 恢复。**双递归因此在机理上正确,而不是靠三地址改写规避**(A2 修复,见 §5)。

push/pop 机器自身用的临时单元在生成保护代码时**清空 free-list 后新分配**,保证其名字不落入
已快照的 `protect(F)`,不会"在 push 某单元的同时又写该单元"。

### 3.3 生成顺序

镜像 `c2mg.parse_program`:先把所有例程体生成到一个 `Generator`(此过程会创建 push/pop 用的
新 temp、新常量,并向 `self.flags` 追加所需 flag),**再**发射头部(全局 `VAR` 排序 →
`FLAG` → `PROTO` 排序),最后拼接。这样生成期新增的每函数 temp 落在各自 `DEF` 内、新增全局
常量/flag 被头部捕获。`main` 不可被调用 → 永不成环 → **永不被保护**;非 `main` 例程若体末非
`return`,补一条隐式 `return 0`(避免落到自动追加的 `END` 把整个程序提前终止,见 mg-spec §4.8)。

## 4. 语言子集与 v0 取舍

严格对齐 py2c v1:int 变量与算术(`+ - * // %`,常量折叠 mod 3^20)、`while`、
`if/elif/else`、`for`-`range`、链式比较、布尔 `and/or/not`、函数定义/调用/`return`、递归
(含双递归、互递归)、`putchar/getchar/ord`。已知 v0 取舍(记入模块 docstring):

- **`and`/`or` 非短路**:复用 c2mg 的位式 `_logical_and/_logical_or`,两侧恒求值。仅当布尔
  操作数**有副作用**时与 Python 语义不同;实测子集里布尔操作数均为纯值比较,输出不受影响。
- 函数名沿用 c2mg 约定**大写**(`fib`→`FIB`);局部 `u_` 前缀。名字合法性检查同 py2c
  (拒绝 `zz` 前缀、C 关键字、`main/putchar/getchar` 保留)。

## 4.1 诊断契约(对齐 `docs/python-subset-spec.md` §3,不复刻 py2c 缺陷)

py2mg 是**全新前端**(未复用 py2c 的 AST 处理代码),因此可以直接规避
`tmp/subset-spec/defects.md` 记录的 py2c 静默错译(C 类)缺陷。所有拒绝均抛
`Py2MgError`,携带**原始 Python 源码**的准确 `lineno` 与源码片段,无裸 traceback:

| 缺陷 | py2c 行为 | py2mg 行为 |
|---|---|---|
| C1 顶层 `return` | 静默接受(死代码判断) | 拒绝 `'return' outside function`(`_stmt_Return` 的 `_is_main` 分支,非死代码) |
| C2 裸注解后读取 `x: int` | 静默零初始化 | 裸注解不绑定(`_collect_assigned`);读取报 `name 'x' is not defined` |
| C3 未初始化 `x += 1` | 静默零初始化 | 定值分析报 `name 'x' may be used before assignment` |
| C4 装饰器 | 忽略 | 拒绝 `function decorators are unsupported` |
| C5 `global x` 与形参 `x` 同名 | 静默接受 | 拒绝 `name 'x' is parameter and global` |
| D6-D9 条件/循环内赋值后读取 | 无定值分析,静默错译 | **流敏定值分析**:if 两分支交集、while/for 体后不算已绑定,报 `may be used before assignment` |
| D13 函数名 `print/range/ord/chr` | 可定义、调用被内建分支误拦 | 注册时即拒绝 `collides with a builtin` |

**定值分析**(`_check_definite_assignment`)是一遍简单的流敏分析,镜像 CPython 规则:
一个名字的读取必须在**到达该读取的每条路径上**都已绑定。`if/else` 取两分支绑定集的
交集(某分支必 `return` 则取另一分支);`while`/`for` 体可能零次执行,故循环体内的赋值
在循环后不算已绑定(`for` 变量同理)。函数可读取"稍后才在模块级赋值"的全局(运行期在
调用时才绑定,与 CPython 一致),故不误拒前向全局引用。

## 5. A2 双递归 bug 的机理修复(验证)

`return fib(n-1) + fib(n-2)`:直连**不做**三地址改写,自然嵌套求值——`fib(n-1)` 的返回值暂存
在 temp `t` 中,`_live` 在求值 `fib(n-2)` 期间持有 `t`,故第二次 `CALL FIB` 点把 `t` 记入
`FIB` 的跨调用保护集。运行 `fib(5)` 直连产物,输出 `A`(fib(5)=5,+60),与期望一致——
双递归正确。对照 `docs/findings.md` §A2:手写 C 的内联双递归在上游被误编译(fib(4)=2),
而直连从机理消除该 bug,无需依赖 py2c 的三地址守卫。

## 6. 体积对比数据

方法:每个用例经两条路径生成 `.mg`,再经 `scripts/mg2mb.sh -s 1`(ref 工具链)汇编成 `.mb`,
用参考 C 解释器与 pyMalbolge 运行。**输出逐字节一致**(下表 `out` 列),`.mb` 本身不要求一致。

| 用例 | `.mg` 行数 c / direct | `.mb` 字节 c / direct | direct/c | 两后端输出一致 |
|---|---|---|---|---|
| putchar_hi | 20 / 19 | 585,997 / 585,151 | 1.00 | ✓ `Hi` |
| echo_getchar | 113 / 34 | 5,065,849 / 1,258,379 | **0.25** | ✓ `Q` |
| if_else | 269 / 108 | 12,125,907 / 4,695,019 | **0.39** | ✓ `Z` |
| for_range | 586 / 253 | 27,335,859 / 11,912,339 | **0.44** | ✓ `ABC` |
| while_countdown | 619 / 287 | 28,927,937 / 13,604,715 | **0.47** | ✓ `CBA` |
| multiply_folded | 14 / 13 | 383,803 / 382,957 | 1.00 | ✓ `A` |
| recursion_single | 1,790 / 802 | 81,805,475 / 37,875,891 | **0.46** | ✓ `A` |
| recursion_fib(**双递归**) | 2,407 / 1,201 | 110,468,331 / 56,839,263 | **0.51** | ✓ `A` |
| runtime_multiply | 2,495 / 1,283 | 115,190,985 / 61,438,401 | **0.53** | ✓ `0`(注) |
| runtime_divmod | 3,389 / 1,806 | 156,944,657 / 86,842,371 | **0.55** | ✓ `CC` |
| mutual_recursion | 2,674 / 1,251 | 121,641,641 / 58,327,753 | **0.48** | ✓ `A` |

> `.mb` 字节经 `scripts/mg2mb.sh -s 1`(ref 工具链)汇编、参考 C 解释器运行采集;
> putchar_hi、echo_getchar 两例额外在 pyMalbolge 上交叉核对,双递归 recursion_fib
> 也在 pyMalbolge 上直接运行确认输出 `A`。`out` 列是**两条路径各自运行的输出逐字节相同**。

**小结**:

- 直连路径在所有已测用例上 `.mb` **不大于** C 路径;含控制流/函数/递归的用例普遍**小 40~75%**。
- 主要节省来源:(a) 真实递归分析——非递归函数(含 `main`、`zzmul` 等)**零** push/pop;
  (b) `if/while` 条件直接喂 `SWITCH`,免去 py2c 的 bool→int 0/1 控制流物化;
  (c) 无三地址中间局部与拷贝。
- 体积**近乎持平**的两例(putchar_hi、multiply_folded)本就无函数调用、无控制流、乘法被折叠,
  两条路径生成的原语序列几乎相同,符合预期。
- **`multiply_folded` 的教训**:早期实现预扫描 AST 只要出现 `* // %` 就注入 helper,导致被
  常量折叠掉的 `9*7` 仍白白注入 1000+ 行 `ZZMUL`(`.mb` 一度 49.7 MB)。改为**懒注入**
  (仅真正发射 helper 调用时才注册编译)后回到 382 KB,与 C 路径持平。
- 注:`runtime_multiply`(`n*m+48-42`,n=6,m=7)两后端都输出 `'0'`(=48),彼此逐字节一致;
  这正是正确值(采集脚本里的期望字节曾误写为 `T`,与程序无关)。

## 7. 验收

- 单测:`test/test_py2mg.py`(生成结构、递归分析、帧策略、mg2mc 接受、错误拒绝),27 项,纯
  Python 无外部依赖。
- 双后端对拍 e2e:`test/test_py2mg_e2e.py`,每用例两路径编译到 `.mb` 运行,输出逐字节一致
  (含双递归 fib、互递归)。有 ref 工具链时走快速构建。
- 现有行为零破坏:`--backend` 默认 `c`,`compile_python_to_mb` 默认 `backend="c"`;
  py2c/c2mg/mg2mc/mc2mb 未改。

## 8. 遗留问题 / 后续

- **`and/or` 短路**:v0 非短路,副作用操作数场景语义与 Python 不同(见 §4)。v1 可用嵌套
  `SWITCH` 物化短路。
- **保护集进一步收紧**:当前对递归函数保护"全部非静态局部";可加"仅跨调用存活的局部"活性
  分析进一步缩小递归函数体积(temp 已精确,局部尚保守)。
- **mg+ 数组方言**:v0 不涉及;为数组阶段(`IND_OPR` 手写栈/下标)预留了直连口子。
