# pyMalbolge Python 子集 v1 规范

> [English](python-subset-spec.md) | **中文**

> 规范对象:`malbolge/compiler/py2c.py`(Python 子集 → 名古屋高层 C 子集的转译
> 前端,函数 `compile_python_to_c`)。原始审计以该文件的**源码行为**为事实来源；
> 十进制 I/O 补充契约覆盖两个前端，不满足于 `docs/design/highlevel-to-malbolge.zh.md` §5 的概述性描述。
> 版本:v1，2026-10-08 补充两个前端 `py2c.py` / `py2mg.py` 的 Python QoS 修复与运行时无符号
> 十进制 I/O 契约（§1.7–1.9）。原源码行号与附录审计保留 `02c0b82` 时的
> 历史快照（957 行），不代表当前源码位置。

## 0. 术语与定位

- "接受(accept)":`compile_python_to_c(source)` 返回字符串(C 源码),不抛异常。
- "拒绝(reject)":抛出 `malbolge.compiler.CompileError`,携带 `lineno`/`col`/
  可读 `message`,且不泄漏 Python 原生 traceback。
- 原始审计覆盖 **py2c 这一级前端**；§1.7–1.8 的十进制 I/O 契约适用于
  两个 Python 前端。下游 `c2mg.py`(→ .mg)、`mg2mc.py`
  (→ .mc)、`mc2mb.py`(→ .mb)有各自独立的错误类型(`C2MgError` 等),不在本
  规范范围内,但附录的诊断审计会指出"py2c 本该拒绝、却把错误转嫁给下游"的
  情形,因为这直接影响用户能否看懂错误。
- "值环"指 Malbolge20 的运算环:所有整数按 `mod 3**20`(`MOD = 3486784401`)
  归约,是非负整数环,没有负数概念。

---

## 1. 接受集合

### 1.1 模块(Module)顶层语句

`compile()` (`py2c.py:860-931`) 对 `ast.parse(source).body` 的每条顶层语句分派:

| 顶层语句形态 | 处理 |
|---|---|
| `ast.FunctionDef` | 注册为用户函数(见 §1.3),不允许出现在合成 `main()` 里 |
| `Expr(Constant(str))` 为首条语句 | 模块文档字符串，忽略；模块/函数 docstring 位置之外的裸字符串拒绝 |
| `ast.Import` / `ast.ImportFrom` | 拒绝:`"'import' is unsupported"` |
| `ast.ClassDef` | 拒绝:`"class definitions are unsupported"` |
| 其他任意语句 | 收集进 `module_body`,作为合成 `main()` 的函数体逐条编译(适用 §1.2 的语句子集) |

顶层不允许出现名为 `main` 的函数定义(编译器自己合成 `main()`):
`"define top-level code directly, not a main() function ..."`。

### 1.2 语句(Statement)

`compile_stmt` (`py2c.py:531-536`) 按节点类型名查找 `_stmt_<TypeName>` 方法;
找不到即拒绝(`"unsupported statement: {TypeName}"`)。**已实现**(即接受)的
语句类型如下,每条附限制:

| AST 节点 | 方法 | 接受形态与限制 |
|---|---|---|
| `Assign` | `_stmt_Assign` 与共享正规化 | 裸名字目标，或与显式固定长度平坦 tuple RHS 匹配的平坦名字 tuple 目标；支持交换与多组 tuple 链式目标，以临时量降级而非创建运行时 tuple。完整 RHS 求值并保存后才写目标；普通 `a = b = expr` 只求值一次 |
| `AnnAssign` | `_stmt_AnnAssign` | 目标须为裸名字；忽略注解。裸 `x: int` 不绑定值，后续读取仍须通过确定赋值检查 |
| `AugAssign` | `_stmt_AugAssign` | 裸名字目标，仅 `+= -= *= //= %=`；先保存旧目标值，再求 RHS，即使其中的调用修改同名全局变量。运行时零除契约见 §1.9 |
| `Expr` | `_stmt_Expr` | 接受作为语句的 `putchar(x)` 与 `print(...)` 调用；其他能被 `lower()` 接受的表达式计算后丢弃返回值（含裸数字字面量与裸变量名） |
| `If` | `_stmt_If` | `test` 走条件物化(§1.4);`elif` 是 AST 层面的嵌套 `If`,天然支持 |
| `While` | `_stmt_While` | 不支持 `while...else`(拒绝);条件在循环入口和每轮循环体末尾各求值一次 |
| `For` | `_stmt_For` | 仅 `for <Name> in range(...)`，不支持循环 `else`。绑定目标之前一次求值并保存边界；步长须为非零整数字面量，允许负步长。隐藏迭代器不受循环体对可见目标的赋值影响；空循环保留先前目标值，非空循环保留循环体最后赋给目标的值。无符号边界/倒序细节见 §1.9 |
| `Return` | `_stmt_Return` | 支持整数返回值；裸 `return`、`return None` 与落空仅可用于结果被丢弃的 void 调用。可能返回 None 的函数结果不能作为标量使用（§1.9）；模块级 return 拒绝 |
| `Pass` | `_stmt_Pass` | no-op |
| `Global` | `_stmt_Global` | 不得与形参冲突，也不得位于该作用域同名变量的先前读取/赋值之后；Python 语法校验在原源码位置拒绝冲突 |
| `Break` | `_stmt_Break` | **批次一(2026-07-23)起接受**:仅限循环体内(`while`/`for`),经标志变量降级实现(每个含 break/continue 的循环分配 `skip`+`brk` 两个标志,循环体每条语句包 `if(skip==0)` 守卫);嵌套循环各自独立标志,`break` 只终止最内层循环并跳过 `for` 步进;循环外使用拒绝:`"'break' outside loop"` |
| `Continue` | `_stmt_Continue` | 同上;`continue` 跳过本轮剩余语句,`for` 的步进**仍执行**;循环外拒绝 |
| `FunctionDef`(嵌套) | `_stmt_FunctionDef` | 无条件拒绝:`"nested function definitions are unsupported"` |

未在上表的语句类型(`ClassDef` 嵌套、`Import`/`ImportFrom` 嵌套、`Try`、
`With`、`Assert`、`Delete`、`Raise`、`Match`、`AsyncFunctionDef`、`TypeAlias`
等)一律落到 `compile_stmt` 的通用拒绝分支:`"unsupported statement:
{TypeName}"`。

### 1.3 函数定义(`ast.FunctionDef`,顶层)

`_register_function` (`py2c.py:933-947`) + `_compile_function`
(`py2c.py:811-858`):

- 仅接受**简单位置参数**:`node.args.vararg`(`*args`)、`kwarg`(`**kwargs`)、
  `kwonlyargs`(`*, x`)、`posonlyargs`(`x, /`)、`defaults`/`kw_defaults`
  (默认值)任意一项非空,一律拒绝:`"only simple positional parameters are
  supported ..."`。
- 函数名与参数名都要通过 `check_var_name`(§1.6 标识符规则)。
- 函数名做**大小写不敏感的唯一性检查**:两个 Python 函数名转大写后相同即冲突
  (`"function {!r} collides with {!r} (function names are case-insensitive in
  the target backend)"`),因为下游后端统一把函数名转大写。
- 函数名转大写后落在 `RESERVED_FUNCS = {"MAIN", "PUTCHAR", "GETCHAR",
  "ZZMUL", "ZZDIV", "ZZMOD"}` 里即拒绝;但注意 `main`/`putchar`/`getchar` 这三个
  **小写原形**会先被 `check_var_name`(通过 `C_KEYWORDS`)拦下,`RESERVED_FUNCS`
  对它们只在**大小写变体**(如 `Main`、`PUTCHAR`)时才真正触发,详见附录审计
  `sem_func_named_main_case_variant`。
- 重复定义同一个函数名拒绝:`"function {!r} is already defined"`。
- 参数/返回类型注解被忽略；装饰器拒绝，`AsyncFunctionDef` 仍不支持。
  固定签名函数接受简单位置与命名实参；默认值与拆包不支持。
- 函数体内的语句子集与 §1.2 相同;不允许嵌套 `def`(§1.2 已列)。
- 所有用户函数在编译任何函数体**之前**统一注册完毕,因此互相调用不受源码中
  定义顺序限制(含直接/间接递归);生成的 C 源码为每个用户函数发射前向原型。

源码调用区分大小写：`foo()` 不解析为 `FOO()`。目标名称归一化导致的
定义碰撞仍拒绝；`end` 等目标保留函数名在原源码定义行报错，不等到生成
目标代码之后。

### 1.4 表达式(Expression)

`lower()` 处理以下节点类型,每种展开如下;不在此列的节点类型(`List`、
`Dict`、`Set`、`Tuple`、`ListComp`/`SetComp`/`DictComp`/`GeneratorExp`、
`Lambda`、`Attribute`、`Subscript`、`Slice`、`Starred`、`NamedExpr`、
`Yield`/`YieldFrom`、`Await` 等)一律落到通用拒绝:`"unsupported
expression: {TypeName}"`。`JoinedStr`(f-string)例外:**仅在 `print()`
实参位置**接受（字面量文本与整数部件；conversion/format specifier 拒绝，见 §1.7）；其他位置维持
"unsupported expression: JoinedStr" 拒绝。

| AST 节点 | 接受形态 |
|---|---|
| `Constant` | 见 §1.5 常量子表 |
| `Name`(`Load` 上下文) | 名字须合法，且在读取处已确定赋值；保守检查分支/循环的不确定性，字面量真值按无符号值环归约 |
| `BinOp` | 见 §1.5 运算符子表;编译期能折叠的常量表达式直接折成整数字面量(mod 3**20),否则降为三地址式(至多一个二元运算) |
| `UnaryOp` | `+x` 原样返回 `lower(x)`;`not x` 走条件物化;`-x`/`~x` 拒绝(见 §1.5) |
| `BoolOp`（`and`/`or`） | 惰性求值并返回被选中的操作数，符合 Python；不会仅因是布尔运算就归一化为 0/1 |
| `Compare` | 接受 `< <= > >= == !=`，比较结果物化为 0/1。链式比较对每个实际到达的操作数只求值一次，保存共享中间值，仅当前面比较成功时才求后续操作数；`is`/`is not`/`in`/`not in` 仍拒绝 |
| `Call` | 见 §1.7 内建函数与 §1.3 用户函数调用 |
| `IfExp`(`a if c else b`,批次一新增) | 物化为 temp + 真实 `if/else` 双分支,**惰性求值**:仅被选中分支的副作用(如函数调用)发生 |

**条件物化**：比较与 `not` 在需要结果值时物化为整数 0/1，避开下游 C
bool 类型。`and`/`or` 保留操作数返回语义并惰性分支；条件中零为假、非零
无符号字为真。较早的表达式操作数与调用实参会先保存，避免之后的副作用改变
它们原先读取的值。

### 1.5 常量与运算符子表

**常量(`ast.Constant`)**,`_const()` (`py2c.py:261-278`):

| Python 值类型 | 处理 |
|---|---|
| `bool`(`True`/`False`) | 折成整数 `1`/`0`(不发射 `bool`/`true`/`false`,见 §2) |
| `int`,`v >= 0` | 折成 `v % MOD` |
| `int`,`v < 0` | 拒绝(见下方"负数"行) |
| `str` | 一般表达式位置拒绝:`"string literals are unsupported ..."`。**三个例外**:`ord('c')` 的单字符实参;`print()` 实参/`sep=`/`end=` 位置的字符串字面量(编译期展开,见 §1.7)；`int(input("prompt"))` 中的字面量提示语。另见 §1.2 docstring 位置规则:模块/函数体首条裸字符串被静默忽略 |
| `float` | 拒绝:`"floating-point values are unsupported"` |
| 其他（`bytes`、`complex`、`Ellipsis`、`None` 等） | 作为标量常量拒绝；`return None` 是明确的 void 返回例外（§1.9） |

**二元运算符(`ast.BinOp.op`)**,`_binop`/`_fold`/`_binop_emit`
(`py2c.py:280-333`):

| 运算符 | 接受? | 说明 |
|---|---|---|
| `+` `-` | 是 | 直接发射 `+`/`-`;结果按 mod 3**20 归约(减法用 Python `%` 的非负语义,天然匹配值环) |
| `*` | 是 | 编译期可折叠则直接算;否则按需注入 `zzmul` 辅助函数(倍增法,~32 次加法) |
| `//` | 是 | 常量折叠或降级为除法辅助函数；已知零除数抛 CompileError，动态零除数设置共享错误标志并退栈到 main（§1.9），不再静默返回 0 |
| `%` | 是 | 常量折叠或降级为取余辅助函数；零除数与 `//` 使用相同的编译期/运行时错误契约 |
| `/` | 否 | 拒绝:`"true division '/' is unsupported; use floor division '//' ..."` |
| `**` `&` `\|` `^` `<<` `>>` | 否 | 拒绝:`"unsupported binary operator: {Pow|BitAnd|BitOr|BitXor|LShift|RShift}"` |

**一元运算符(`ast.UnaryOp.op`)**,`_unaryop` (`py2c.py:335-349`):

| 运算符 | 接受? | 说明 |
|---|---|---|
| `+x` | 是 | 原样透传 |
| `not x` | 是 | 走条件物化 |
| `-x` | 否 | 拒绝:`"unary minus is unsupported: the value ring has no negatives ..."`;字面量 `-5` 在 AST 里同样是 `UnaryOp(USub, Constant(5))`,走同一路径,报同一条消息 |
| `~x` | 否 | 拒绝:`"bitwise '~' is unsupported"` |

**比较运算符(`ast.Compare.ops`)**,`_CMP_OP` (`py2c.py:451-454`):

接受 `< <= > >= == !=`;拒绝 `is` `is not` `in` `not in`
(`"comparison operator {Is|IsNot|In|NotIn} is unsupported"`)。

**负数**：除 §1.9 的 range 字面量边界/步长例外外，v1 在字面量与一元负号
两条路径上都**静态拒绝**负数(值环本就没有
"负"这个概念,`3 - 5` 会折成一个很大的正数而不是 -2)。没有其他产生负数的
途径(减法结果本身不受限制,只是运算符两侧的字面量输入被挡住)。

### 1.6 标识符规则

`check_var_name` (`py2c.py:190-206`),对变量名、参数名、函数名(函数名额外
过 `check_func_name`)、`global` 声明的名字统一适用:

1. 必须非空,首字符 `isalpha()` 且**整个字符串 `isascii()`**(unicode 标识符
   在 Python 3 语法层面合法,但这里会被拒绝:`"identifier {!r} is not a valid
   C identifier"`)。
2. 除首字符外,每个字符必须是 `isalnum()` 或下划线,且整体仍需 ascii(与上一
   条有重叠,是同一份 ascii 约束的第二次校验)。
3. 大小写不敏感的 `zz` 前缀保留给编译器内部临时变量/辅助函数(`zzt0`、
   `zzmul` 等):任何用户标识符 `name.lower().startswith("zz")` 一律拒绝
   (`"identifier {!r} is reserved (names starting with 'zz' are used
   internally by the compiler)"`)——`zz`、`ZZ`、`Zz`、`zZ` 各种大小写都命中。
4. 精确匹配(大小写敏感)`C_KEYWORDS = {"int", "bool", "true", "false", "if",
   "else", "while", "return", "static", "main", "putchar", "getchar"}` 中任
   一个即拒绝(`"identifier {!r} collides with a C keyword in the target
   backend"`)。注意这是**精确字符串匹配**,`INT`/`While_`/`Main`(大写变体)
   不在此列——`main`/`putchar`/`getchar` 的大写变体转而由 §1.3 的
   `RESERVED_FUNCS`(仅函数名适用)或压根不受限制(变量名场景)。
5. 函数名额外检查:见 §1.3 的大小写唯一性与 `RESERVED_FUNCS`。

合法的**变量名**示例有 `print`、`range`、`ord`、`chr`、`input`、
`while_` 与 `INT`。内建调用名（含 `input`、`int`）不能用作用户函数名；
原先“能定义、不能正常调用”的缺陷已修复（D13）。

### 1.7 内建函数(仅在 `Call` 节点里可用)

`_call()` (`py2c.py:351-398`) 按被调用者名字(必须是裸 `ast.Name`,
"only direct function calls are supported (no methods or computed
callees)")分派:

| 调用形式 | 接受? | 说明 |
|---|---|---|
| `putchar(x)` | 仅作为语句 `putchar(x)`(`_stmt_Expr` 专门处理);单参数、无关键字参数 | 用作表达式值(`y = putchar(x)`)拒绝:`"putchar() returns nothing and cannot be used as a value"` |
| `getchar()` | 是 | 零参数,无关键字参数(否则报 `"getchar() takes no arguments"`) |
| `ord(c)` | 是,但 `c` 必须是**编译期字面量**、且是长度恰为 1 的字符串常量(`ast.Constant(str)`),在编译期直接折成 `ord(c) % MOD` | 非字面量参数报 "... (evaluated at compile time)";长度 ≠ 1 报 "expects a single character" |
| `chr(x)` | 否 | 拒绝:`"chr() is unsupported; emit characters with putchar(codepoint)"` |
| `print(...)` | 作为语句接受：无符号整数表达式、字符串字面量、基本 f-string | 实参可混用；f-string 部件为字面量文本或整数表达式，从左到右只求值一次；`!r`/`!s`/`!a` 与格式规格拒绝。`sep=`/`end=` 须为静态字符串字面量（默认 `" "`/`"\n"`）。全部实参值保存后才输出本次 print 文本；codepoint >255 与作为表达式值的 print 拒绝 |
| `int(input())` / `int(input("prompt"))` | 模块与用户函数作用域均接受 | 解析无符号 ASCII 十进制；提示语须为 codepoint `0..255` 的字符串字面量，无 input 关键字参数；错误经调用方传播，仅 main 报告一次，见 §1.8–1.9 |
| `input()` / 其他 `int(...)` | 拒绝 | 返回字符串的原始 input 与一般整数转换不支持；仅接受嵌套的 `int(input(...))` 形式 |
| `range(...)` | 仅作为 `for` 循环头 | 在其他任何表达式位置调用 `range(...)` 一律拒绝:`"range() is only valid in a 'for' loop header"` |
| 用户函数名 | 是 | 固定签名支持位置实参与简单关键字实参；先按源码顺序求值并保存，再按形参顺序重排。缺失/重复/未知参数与 `*`/`**` 拆包拒绝 |
| 其他任意名字(未注册的用户函数) | 否 | `"call to undefined function {!r}"` |

内建调用分派先于用户函数查找。以内建调用名定义函数会在注册阶段拒绝
（D13）；附录记录的名称遮蔽陷阱属于已修复的历史缺陷。

### 1.8 运行时无符号十进制 I/O（2026-10-08）

两个前端仅在源码需要运行时整数输出或 `int(input(...))` 时注入十进制辅助函数。
源码无需自行实现 `getchar()`/`putchar()` 转换或声明辅助函数。

- `print(x)` 输出值环中当前的无符号值 `0..3486784400`，包含零，不带符号或
  多余前导零。模块与函数内均支持运行时表达式、函数调用结果。字符串字面量可
  与数值实参混用，如 `print("result", fib(n), sep=": ")` 或
  `print(f"result: {fib(n)}")`。基本运行时整数 f-string 仅限 print 实参；
  conversion 与格式规格仍拒绝。
- 输入仅接受 `int(input())` 与 `int(input("字面量提示语"))`。可出现在顶层
  表达式、循环和条件中，也支持用户函数内使用。提示语在读取前输出，不自动
  加换行。原始 `input()` 字符串、变量提示语、`int(x)`、`int("12")` 与
  其他进制转换均拒绝。
- 输入读取至 LF 或 EOF。值须包含至少一个 ASCII 数字 `0..9`，可带前导 `+`
  及前后 ASCII 空格、tab、vertical tab、form feed、CR。CR 是空白而非独立
  行分隔符；支持 CRLF。符号与数字之间或数字内部的空白非法。接受前导零；
  负号、下划线、Unicode 数字及大于 `3486784400` 的值在运行时拒绝，不回绕。
- 有效值之后的 EOF 正常结束输入；空输入、仅空白、值之前的 EOF、格式非法
  或溢出立即经用户函数调用链退栈，最终仅 main 输出 `error\n` 并终止，后续操作
  不再执行。之前
  已发生的副作用（含输入提示语）保留。不引入 Python `ValueError`/`EOFError`
  或异常机制，也不构造运行时字符串（见 D18）。

### 1.9 Python QoS 契约（2026-10-08）

- 平坦 tuple 赋值要求匹配的裸名字目标与显式平坦 tuple RHS，如 `a, b = b, a`。
  先保存所有值再写目标；嵌套 tuple、starred 元素及任意表达式拆包均拒绝，
  不引入运行时 tuple/list 对象。
- 简单关键字函数调用先按源码顺序求值，再绑定到固定形参；默认值、`*args`、
  `**kwargs` 及重复/缺失/未知参数不支持。
- `range()` 保存起止边界并使用隐藏迭代器。起点与非负边界位于无符号值环；
  允许负整数字面量步长。倒序字面量终点 `-1` 包含零，但倒序终点小于 `-1`
  或初始起点为负拒绝。正序负字面量终点归为零，仍保留起点表达式副作用。
  步长绝对值至少为 `3**20` 时最多迭代一次；无符号更新回绕前先检查边界。
- 输入失败与动态除法/取余零除数设置共享错误标志，函数立即返回，调用方继续
  执行前检查该标志，逐层传播；仅 main 输出 `error\n` 并终止。不引入 Python
  异常对象或捕获机制；已知常量零除数可在编译期拒绝。
- 任一可达路径存在裸/None 返回或落空的函数，可作为结果被丢弃的语句调用；
  不能把结果用于整数表达式、条件、参数、赋值或有值 return。能证明只返回值
  的路径可接受；不可达字面量分支按值环真值判定。内部 void 的零返回不构成
  源码层面的返回值承诺。
- 一般有符号整数、任意运行时对象/字符串、通用 `int()` 转换及返回字符串的
  原始 `input()` 仍不属于该子集。

---

## 2. 语义偏差表(与 CPython 对比)

> 编号说明:本节 `D1`-`D19` 是本文档自用的偏差编号,与 `defects.md` 里独立
> 编号的 `C1`-`C5`(静默接受类缺陷)、`B1`-`B6`(诊断质量差类缺陷)是两套不同
> 的编号体系——`defects.md` 按严重度排列缺陷,本表按 CPython 语义主题排列
> 偏差(含"设计性偏差"与"缺陷"两种,后者才对应 `defects.md` 的条目)。带
> "缺陷"标记的行在备注列给出了对应的 `defects.md` 编号。

| # | 主题 | CPython 语义 | py2c v1 语义 | 分类 |
|---|---|---|---|---|
| D1 | 整数环 | 任意精度有符号整数 | 所有整数在 `mod 3**20` 的非负环里;`+ - *` 结果、字面量、`ord()` 结果均归约 | 设计性偏差(已文档化) |
| D2 | 负值 | 支持有符号值 | 除 §1.9 的 range 边界/步长字面量例外外，静态拒绝一元负号/负字面量；运行时算术值仍为无符号 | 设计性偏差（已文档化） |
| D3 | `/` vs `//`/`%` | `/` 真除法返回 float,`//`/`%` 对负数做"向下取整"语义 | 只有 `//`/`%`,对非负整数做长除法;`/` 直接拒绝 | 设计性偏差(已文档化) |
| D4 | 布尔值 | 独立 bool 类型；比较返回 bool；and/or 返回被选操作数 | bool 字面量折为 1/0；比较/not 物化整数 0/1，and/or 惰性返回被选无符号操作数；不发射独立运行时 bool 对象 | 设计性偏差（规避下游 bool 缺陷） |
| D5 | `getchar`/`putchar` 与 EOF | 无对应内建；需要 `sys.stdin`/`sys.stdout` | 原始 `getchar()`/`putchar()` 保持字节 I/O；Malbolge20 的 EOF 哨兵值为 `59049`。共享十进制读取辅助函数显式识别该值（§1.8），不改变原始 `getchar()` 返回值 | 设计性偏差（已文档化） |
| D6 | 未绑定变量读取(函数作用域) | `NameError`/`UnboundLocalError`(运行时) | **已修复(2026-07-22)**:`lower(Name)` 的 `Name`(Load)分支现在会查询一个按实际编译顺序推进的"已确定赋值"集合(`self.bound`,函数级读取额外放行任何模块级已赋值名字,见 `_is_bound`),未命中则以准确的原始 Python 行号、使用用户书写的原始标识符拼写抛出 `CompileError`("name {!r} is used before it is assigned")——见 `defects.md` B1/B2(已修复) | 已修复(2026-07-22,原 B 类缺陷) |
| D7 | 未绑定变量读取(模块作用域) | 同上 | **已修复(2026-07-22)**:同 D6 的机制;合成 `main()` 内不享有"模块级已赋值名字"的兜底放行(因为 `main()` 本身就是模块级代码的顺序执行),严格按声明顺序检查 | 已修复(2026-07-22,原 B 类缺陷) |
| D8 | 增量赋值目标须已绑定 | `x += 1`(`x` 未定义)是 `NameError` | **已修复(2026-07-22)**:`_stmt_AugAssign` 在生成 `x += ...;` 之前先查询"已确定赋值"集合,未绑定则拒绝(见 `defects.md` C3,已修复) | 已修复(2026-07-22,原 C 类缺陷) |
| D9 | 裸类型注解 `x: int` | 不绑定名字(只写 `__annotations__`);后续读取是 `NameError` | **已修复(2026-07-22)**:裸注解分支不再调用 `_bind_target`,只做标识符合法性校验,不建立绑定;后续读取落入 D6/D7 同一条检查路径(见 `defects.md` C2,已修复) | 已修复(2026-07-22,原 C 类缺陷) |
| D10 | 模块外 `return` | `SyntaxError: 'return' outside function`(编译期,由字节码编译器而非 `ast.parse` 检查) | **已修复(2026-07-22)**:`_stmt_Return` 改为判断 `self.in_main`(此前判断恒假的死代码 `self.locals is None`),顶层 `return` 现在会被准确拒绝(见 `defects.md` C1,已修复) | 已修复(2026-07-22,原 C 类缺陷,曾是最严重一条) |
| D11 | 装饰器 | 对函数对象做实际变换 | **已修复(2026-07-22)**:`_register_function` 现在检查 `decorator_list`,任何非空装饰器列表都会被拒绝(见 `defects.md` C4,已修复) | 已修复(2026-07-22,原 C 类缺陷) |
| D12 | `global x` 与形参 `x` 同名 | `SyntaxError: name 'x' is parameter and global` | **已修复(2026-07-22)**:`_stmt_Global` 现在会与 `self.params` 比对,命中则拒绝(见 `defects.md` C5,已修复) | 已修复(2026-07-22,原 C 类缺陷) |
| D13 | `range(...)`/`print(...)`/`ord(...)`/`chr(...)` 作为用户函数名 | 合法,遮蔽内建;调用走用户函数 | **已修复(2026-07-22)**:`check_func_name` 新增 `BUILTIN_CALL_NAMES` 保留字检查,在函数**注册**阶段就以准确行号拒绝,不再放行到调用点才报出文不对题的错误(见 `defects.md` B3-B6,已修复) | 已修复(2026-07-22,原 B 类缺陷) |
| D14 | 缺失/裸/None 返回 | 可丢弃调用结果；标量使用是否失败取决于实际结果 | 接受结果被丢弃的 void 调用，但可能返回 None/落空的函数结果作为标量使用会在原调用位置拒绝；内部零返回不是可观测的源码值 | 更严格的子集契约（§1.9） |
| D15 | 标识符:非 ASCII / 前导下划线 | 合法(Python 3 标识符规则) | 拒绝(仅接受 `[a-zA-Z][0-9a-zA-Z_]*` 且整体 ASCII) | 设计性偏差(下游 C 词法限制,已文档化) |
| D16 | 模块文档字符串跳过规则 | 仅**首条**语句是字符串常量时才是文档字符串(其余位置的裸字符串语句只是被求值后丢弃,语义等价但概念不同) | **已收紧(2026-07-23,批次一)**:模块与函数体仅**首条**裸字符串按 docstring 静默忽略,与 CPython 的 docstring 概念对齐;其余位置的裸字符串语句现在**拒绝**(CPython 是求值后丢弃)——从"过宽接受"变为"显式拒绝",属设计性偏差(裸字符串在本子集中无任何可产生的效果,拒绝优于沉默) | 设计性偏差(2026-07-23 起,已文档化) |
| D17 | `print()` 常量整数渲染 | `print(3-5)` 输出 `-2`(有符号十进制) | 常量折叠在 mod 3**20 非负环上进行,`print(3-5)` 输出 `3486784398`(D1 偏差在 print 渲染上的显现);正常非负常量与 CPython 一致 | 设计性偏差(D1 的推论,已文档化;带符号整数落地后随 D2 一并消除) |
| D18 | `int(input())` | 一般字符串输入、有符号任意精度转换、Unicode 数字/下划线、非法输入/EOF 抛 Python 异常 | 仅接受 §1.8 的无符号 ASCII 十进制形式，含函数作用域；非法/空/溢出逐层传播至 main，输出 `error\n` 并终止，无运行时字符串或 Python 异常 | 设计性偏差（已文档化） |
| D19 | 运行时零除数 | 抛出 `ZeroDivisionError` | 动态 `//` 或 `%` 零除数逐层传播标志至 main，输出 `error\n` 并终止；已知常量零除数在编译期报错 | 设计性偏差（§1.9） |

**已验证的"看似偏差、实测无偏差"反例**(方法论记录):函数名与模块级同名
全局变量共存(`def foo(): ...` 之后 `foo = 5`)在生成的 C 源码里表面重复声明,
但下游 `c2mg` 会分别发射为 `FOO`(函数)与 `u_foo`(变量),互不冲突,全管线
运行结果与 CPython 实际输出一致。**不要**仅凭中间 C 代码的表面形态判断行为
是否正确,必须验证到下游或跑通全管线 / 对拍 CPython。

---

## 3. 诊断契约

本节是对 py2c v1 现状的**规范性要求**。附录审计发现的 D6/D7/D8/D9/D10/D11/
D12/D13(`defects.md` 的 C1-C5、B1-B6)此前不满足下述第 1 条,已于
2026-07-22 全部修复(见 §2 偏差表各行"已修复"备注与 `defects.md`);当前
`test/test_py2c_diagnostics.py` 的 `TestKnownDefects` 类已把对应的 xfail 全部
翻转为真实断言作为回归锁。

1. **任何不在 §1 接受集合内的输入,必须以 `CompileError` 拒绝,并携带能定位
   到原始 Python 源码的准确 `lineno`**(通过 `node.lineno`,继承自触发拒绝的
   那个 AST 节点)。"准确"指:该行号指向用户能读懂、且确实是问题所在的
   Python 源码行,而不是生成的中间 C/`.mg`/`.mc` 文件里的行号。
2. **禁止 Python 原生 traceback 泄漏**:除了 `ast.parse` 抛出的 `SyntaxError`
   会被 `compile()` 显式捕获并包装成 `CompileError`(见 `py2c.py:860-868`)
   外,编译过程中不应该有任何未捕获的 `AttributeError`/`KeyError`/
   `IndexError`/`TypeError` 等原生异常穿透到调用方——这类异常一旦出现即被
   本审计计为 B 类缺陷("裸异常泄漏")。
3. **禁止静默错译**:一个不在接受集合内的输入,不允许被 `compile_python_to_c`
   无异常地接受并产出结构合法但行为错误的 C 代码(即本文档反复引用的 C 类
   缺陷);也不允许一个**在**接受集合内、语义良好定义的输入产出与本规范 §2
   偏差表不一致的代码。
4. **错误消息格式约定**(`CompileError._render()`,`py2c.py:130-143`):
   ```
   compile error (line <N>): <message>
       <源码那一行,已 strip>
       <col 对齐的插入符 ^ ,若 col_offset 可得>
   ```
   `<message>` 应当:(a) 明确指出违反接受集合的**哪一条**规则;(b) 尽量给出
   替代写法(例如"用 `//` 代替 `/`");(c) 使用用户在源码中实际写下的标识符
   拼写,不使用编译器内部改名(如 `u_foo`、`zzt0`)——D6/D7 此前违反这一条,
   已于 2026-07-22 修复(`CompileError` 消息与行号均取自原始 `ast.Name`
   节点,不经过任何内部改名)。
5. **诊断的作用域边界**:本契约只约束 `compile_python_to_c` 一级前端。若一个
   非法输入被 py2c 错误地放行、只能由下游阶段(`c2mg`/`mg2mc`/`mc2mb`)拒绝,
   即便下游给出的也是一个结构化异常(`C2MgError` 等)而不是裸 traceback,
   仍然违反第 1 条("必须由 py2c 自身、以准确的 Python 源码行号拒绝"),计为
   B 类缺陷而非 A 类。

---

2026-10-08 的 [QoS 验收报告](../notes/python-qos-validation.json)已将
[审计快照](../notes/python-qos-audit.json)结案，覆盖两个编译后端及便携项目
VM 执行。下方历史附录保持原样；本规格不宣称完整 Python、有符号整数或
运行时对象支持。

## 4. 版本节

### v1 实现与分日期补充

- 见 §1 完整接受集合与 §2 偏差表。
- 2026-10-08：两个前端按需注入共享十进制辅助函数，支持运行时无符号整数
  `print()` 与 `int(input([字面量提示语]))`。后续 QoS 工作增加函数内输入、
  基本运行时 f-string、tuple/关键字降级、惰性操作数语义与运行时错误检查
  （§1.9、D14/D18/D19）；有符号整数与运行时字符串对象仍不支持。
- 2026-07-22:D6/D7/D8/D9/D10/D11/D12/D13(`defects.md` C1-C5、B1-B6)全部
  修复。修复方式:
  - `_Compiler` 新增一个按**实际编译顺序**推进的"已确定赋值"名字集合
    (`self.bound`,`_is_bound()`),在 `lower()` 的 `Name`(Load)读取点、
    `_stmt_AugAssign` 的目标预检里统一查询,未命中即拒绝
    (`"name {!r} is used before it is assigned"`)。用户函数额外放行任何
    模块级已赋值名字(`self.module_globals`,`compile()` 里对
    `module_body` 的一次性预扫描),因为读取一个未经 `global` 声明的模块级
    全局在 CPython 里合法;合成的 `main()` 本身就是模块级代码,不享有这条
    放行,必须严格按赋值顺序检查(即 D6/D7/D8/D9 的修复口径)。这是
    `defects.md` 建议的"定值分析"方案的一个简化(近似)版本:按真实编译
    顺序线性推进,不做 `if`/`while`/`for` 分支的交集运算(即仍不能捕获
    "只在某个分支里赋值、之后无条件读取"这类更细的条件绑定错误)——这是
    `defects.md` 根因提要里明确认可的降级选项,换来的是与 py2c 现有"顺序
    编译即在遇到的第一个问题处报错"的行为完全兼容,不改变任何既有 A 类
    诊断测试的报错位置/文案。
  - 裸类型注解(`x: int`)分支不再调用 `_bind_target`(D9)。
  - `_stmt_Return` 判断 `self.in_main` 而非恒假的 `self.locals is None`
    (D10)。
  - `_register_function` 拒绝非空 `decorator_list`(D11)。
  - `_stmt_Global` 与 `self.params` 比对形参同名冲突(D12)。
  - `check_func_name` 新增 `BUILTIN_CALL_NAMES = {"putchar", "getchar",
    "ord", "chr", "print", "range"}` 保留字检查,在函数注册阶段就拒绝
    (D13)。
  - 回归测试:`test/test_py2c_diagnostics.py` 的 `TestKnownDefects` 类,
    原 6 条 `xfail(strict)` 全部翻转为真实断言;`test/test_py2c.py`、
    `test/test_c2mg.py` 现有合法程序用例全部保持不变(不依赖这几类此前
    被静默接受的输入)。
- D14 已按 §1.9 严格限制可能返回 None 的结果使用；原 D5 的 EOF 文档缺口已由明确的
  哨兵值与 §1.8 十进制输入契约补齐。
- 2026-07-23:**批次一语法糖**在 `py2c.py`('c' 后端)与 `py2mg.py`
  ('direct' 后端)按同一语义契约同步实现,两后端对同一源码产生相同程序
  输出(双后端 e2e 对拍验证):
  1. `print()` 常量实参(字符串/可折叠 int/全常量 f-string,`sep=`/`end=`,
     详见 §1.7 与 §2 D17);
  2. f-string(仅 print 实参位置,全常量部件);
  3. `ord('x')`(核实原有实现已符合契约,补测试锁定);
  4. 条件表达式 `a if c else b`(temp + if/else 物化,惰性求值);
  5. `*= //= %=`(核实 py2c 原有实现已支持,补测试;py2mg 侧同步);
  6. `break`/`continue`(标志变量降级,嵌套独立,循环外拒绝);
  7. docstring 位置规则(仅模块/函数体首条,见 §2 D16 收紧)。
  本批次为**纯前端展开**,未新增任何运行时原语;`py2mg` 侧另受
  内部研究日志(private,非本仓库)A3 条记录的 SWITCH 自修改陷阱约束
  (标志走无分支累积 + 单次 SWITCH 模式)。

### v2 计划项(**保留字段** —— 以下未划去的能力仍不在接受集合内,任何试图使用
它们的输入**必须继续被 §3 诊断契约拒绝**,直到对应特性真正实现为止;实现前
私自放宽某一项检查而不同步更新本文档与 §1 接受集合表,视为引入新的 C 类缺陷)

- **带符号整数语义**:引入显式的补码约定或符号位表示,解除 §1.5"负数"行与
  §2 D2 的静态拒绝。
- ~~**运行时无符号十进制 I/O**~~ 已于 2026-10-08 实现运行时整数 `print()`
  与模块/函数内 `int(input(...))`，见 §1.7–1.9。一般返回字符串的
  `input()` 与有符号转换仍不在接受集合中。
- ~~**`break`/`continue`**~~ 批次一(2026-07-23)已实现,见 §1.2。
- **数组/运行时字符串**:`Subscript`/`Slice`/字符串**变量**仍全部拒绝
  (§1.4、§1.5;字符串**字面量**在 print/ord 位置已按批次一放开);数组
  机制解剖与 LOADI/STOREI 设计建议见内部的名古屋数组解剖笔记(private,
  非本仓库)。
- 本表任何一项从"保留、必须拒绝"变为"已实现、加入接受集合"时,必须同步:
  更新本文档 §1 对应小节、在 §2 补充/移除相应偏差表行、在 `defects.md` 里
  确认不会引入新的 D6-D13 式定值分析漏洞(尤其是数组/字符串,一旦引入
  `Subscript` 读写,原本"未绑定变量读取"的定值分析范围需要相应扩大到
  "数组元素/切片是否已初始化",否则会重演 D6-D9 同类问题)。

---

## 附录:诊断审计结果表

审计方法:构造 137 个探测用例(覆盖 §1 每一类不支持的 AST 节点、§2 每一类
已确认或疑似的语义偏差、以及边界值),逐个喂给 `compile_python_to_c`;对
"静默接受但疑似语义错误"的用例,额外喂给 `compile_c_to_mg`/全管线
`compile_python_to_mb` 并在 pyMalbolge 上运行,与直接用 CPython `exec()`
执行等价/近似源码的结果对拍,以确定是否真的存在行为分叉(方法论参考
内部研究日志(private,非本仓库)A4 条的教训:不能只看中间产物"形态可疑"
就下结论)。

分类:A=正确拒绝;B=拒绝但质量差(见 §3 契约第 4/5 条);C=静默接受但语义
错误;D=正确接受。

**总计 137 个用例:A=101,B=6,C=6,D=24。**

脚本与语料:`/Users/anend/.claude/jobs/1d5df563/tmp/subset-spec/probe.py`
(可重跑:`python3 probe.py --summary` 看汇总,`python3 probe.py` 看逐用例
明细,`python3 probe.py --export-md <path>` 重新导出下表)。6 条 B 类 + 6 条
C 类缺陷的详细复现与修复建议见同目录 `defects.md`(已在 §2/§3 交叉引用)。

> **已修复(2026-07-22)**:下表是 `py2c.py` 修复前的历史快照(未重新用
> `probe.py --export-md` 刷新,以保留审计过程的原始记录)。以下 12 个用例
> ID 对应的缺陷已全部修复,当前重新运行 `compile_python_to_c` 会得到
> `CompileError`(而非表中记录的"OK (编译通过)"或错误行号/文案),详见 §2
> 偏差表 D6-D13 各行与 `defects.md`:`ast_decorator_property`、
> `ast_decorator_staticmethod`(C4)、`sem_undefined_var_read_toplevel`、
> `sem_undefined_var_read_func`(B1/B2)、`sem_stray_return_toplevel`
> (C1)、`sem_unbound_augassign`(C3)、`sem_bare_annassign_then_read`
> (C2)、`sem_func_named_range_shadow`、`sem_func_named_print_shadow`、
> `sem_func_named_ord_shadow`、`sem_func_named_chr_shadow`(B3-B6)、
> `sem_global_shadows_param`(C5)。回归测试见
> `test/test_py2c_diagnostics.py::TestKnownDefects`。

<!-- AUDIT_TABLE_START -->
| ID | 输入摘要 | 期望 | 实际 | 备注 |
|---|---|---|---|---|
| `ast_class_toplevel` | `class C: ⏎     pass` | A | CompileError@L1 | ClassDef at module level -> explicit rejection. |
| `ast_class_nested` | `def f(): ⏎     class C: ⏎         pass ⏎     return 1 ⏎ p...` | A | CompileError@L2 | ClassDef inside a function body -> generic 'unsupported statement'. |
| `ast_import` | `import os ⏎ putchar(65)` | A | CompileError@L1 | Import -> explicit rejection. |
| `ast_importfrom` | `from os import path ⏎ putchar(65)` | A | CompileError@L1 | ImportFrom -> explicit rejection (shares the Import branch). |
| `ast_lambda` | `f = lambda x: x + 1` | A | CompileError@L1 | Lambda -> generic 'unsupported expression'. |
| `ast_nested_function` | `def outer(): ⏎     def inner(): ⏎         return 1 ⏎     ...` | A | CompileError@L2 | Nested FunctionDef -> explicit rejection. |
| `ast_closure_free_var` | `def make(): ⏎     y = 1 ⏎     def add(x): ⏎         retur...` | A | CompileError@L3 | Closures require nested defs, same path as ast_nested_function. |
| `ast_generator_func` | `def gen(): ⏎     yield 1 ⏎ putchar(65)` | A | CompileError@L2 | yield -> Expr(Yield) at stmt level, generic 'unsupported expression'. |
| `ast_generator_expr` | `a = (i for i in range(3))` | A | CompileError@L1 | GeneratorExp -> generic 'unsupported expression'. |
| `ast_try_except` | `try: ⏎     x = 1 ⏎ except Exception: ⏎     x = 2 ⏎ putcha...` | A | CompileError@L1 | Try -> generic 'unsupported statement'. |
| `ast_with` | `with open('f') as fh: ⏎     x = 1 ⏎ putchar(x)` | A | CompileError@L1 | With -> generic 'unsupported statement'. |
| `ast_assert` | `x = 1 ⏎ assert x == 1 ⏎ putchar(65)` | A | CompileError@L2 | Assert -> generic 'unsupported statement'. |
| `ast_del` | `x = 1 ⏎ del x ⏎ putchar(65)` | A | CompileError@L2 | Delete -> generic 'unsupported statement'. |
| `ast_nonlocal` | `def outer(): ⏎     x = 1 ⏎     def inner(): ⏎         non...` | A | CompileError@L3 | nested def is hit first (nonlocal only legal inside nested scope anyway). |
| `ast_decorator_property` | `@property ⏎ def foo(x): ⏎     return x ⏎ putchar(foo(65))` | C | OK (编译通过) | decorator_list on a top-level FunctionDef is never inspected by _register_function/_compile_function -- silently dropped. Real CPython: '... |
| `ast_decorator_staticmethod` | `@staticmethod ⏎ def foo(x): ⏎     return x ⏎ putchar(foo(...` | C | OK (编译通过) | Same root cause as ast_decorator_property; staticmethod happens to stay directly-callable on CPython >=3.10 so this particular decorator ... |
| `ast_starargs_def` | `def f(*args): ⏎     return 1 ⏎ putchar(f(1, 2))` | A | CompileError@L1 | vararg -> explicit rejection. |
| `ast_kwargs_def` | `def f(**kw): ⏎     return 1 ⏎ putchar(f())` | A | CompileError@L1 | kwarg -> explicit rejection. |
| `ast_default_arg` | `def f(x=1): ⏎     return x ⏎ putchar(f())` | A | CompileError@L1 | defaults -> explicit rejection. |
| `ast_kwonly_arg` | `def f(*, x): ⏎     return x ⏎ putchar(f(x=1))` | A | CompileError@L1 | kwonlyargs -> explicit rejection. |
| `ast_posonly_arg` | `def f(x, /): ⏎     return x ⏎ putchar(f(65))` | A | CompileError@L1 | posonlyargs -> explicit rejection. |
| `ast_starargs_call` | `def f(a, b): ⏎     return a + b ⏎ args = (1, 2) ⏎ putchar...` | A | CompileError@L3 | Starred in call args -> Starred hits lower()'s generic branch (tuple literal 'args = (1,2)' errors first). |
| `ast_kwargs_call` | `def f(a): ⏎     return a ⏎ putchar(f(a=65))` | A | CompileError@L3 | keyword arg in user call -> explicit rejection. |
| `ast_float_literal` | `x = 3.14 ⏎ putchar(65)` | A | CompileError@L1 | float Constant -> explicit rejection. |
| `ast_str_literal` | `s = 'hi' ⏎ putchar(65)` | A | CompileError@L1 | str Constant (len != 1 case is separate; plain assignment) -> explicit rejection. |
| `ast_bytes_literal` | `b = b'hi' ⏎ putchar(65)` | A | CompileError@L1 | bytes Constant falls through _const()'s bool/int/str/float checks to the generic 'unsupported constant: {!r}' fallback -- correct line, u... |
| `ast_list_literal` | `a = [1, 2, 3] ⏎ putchar(65)` | A | CompileError@L1 | List -> generic 'unsupported expression'. |
| `ast_dict_literal` | `a = {1: 2} ⏎ putchar(65)` | A | CompileError@L1 | Dict -> generic 'unsupported expression'. |
| `ast_set_literal` | `a = {1, 2} ⏎ putchar(65)` | A | CompileError@L1 | Set -> generic 'unsupported expression'. |
| `ast_tuple_literal` | `a = (1, 2) ⏎ putchar(65)` | A | CompileError@L1 | Tuple -> generic 'unsupported expression'. |
| `ast_tuple_unpack_assign` | `a, b = 1, 2 ⏎ putchar(a)` | A | CompileError@L1 | Tuple assignment target -> explicit rejection with node-type name. |
| `ast_starred_assign_target` | `a, *b = 1, 2, 3 ⏎ putchar(a)` | A | CompileError@L1 | Starred target inside a Tuple target -> caught by the same Tuple check (message says 'Tuple', not 'Starred', but still an explicit, corre... |
| `ast_fstring` | `x = 65 ⏎ putchar(f'{x}')` | A | CompileError@L2 | JoinedStr -> generic 'unsupported expression' (inside putchar's arg). |
| `ast_negative_literal` | `x = -5 ⏎ putchar(65)` | A | CompileError@L1 | Constant(-5) parses as UnaryOp(USub, Constant(5)) -> unary-minus path. |
| `ast_unary_negative_var` | `x = 5 ⏎ y = -x ⏎ putchar(65)` | A | CompileError@L2 | UnaryOp(USub) on a non-literal -> explicit rejection. |
| `ast_power_op` | `x = 2 ** 10 ⏎ putchar(65)` | A | CompileError@L1 | Pow -> generic 'unsupported binary operator: Pow'. |
| `ast_bitand` | `x = 5 & 3 ⏎ putchar(65)` | A | CompileError@L1 | BitAnd -> generic 'unsupported binary operator'. |
| `ast_bitor` | `x = 5 \| 3 ⏎ putchar(65)` | A | CompileError@L1 | BitOr -> generic 'unsupported binary operator'. |
| `ast_bitxor` | `x = 5 ^ 3 ⏎ putchar(65)` | A | CompileError@L1 | BitXor -> generic 'unsupported binary operator'. |
| `ast_lshift` | `x = 5 << 1 ⏎ putchar(65)` | A | CompileError@L1 | LShift -> generic 'unsupported binary operator'. |
| `ast_rshift` | `x = 5 >> 1 ⏎ putchar(65)` | A | CompileError@L1 | RShift -> generic 'unsupported binary operator'. |
| `ast_invert` | `x = 5 ⏎ y = ~x ⏎ putchar(65)` | A | CompileError@L2 | Invert ('~') -> explicit rejection. |
| `ast_is` | `x = 1 ⏎ if x is 1: ⏎     putchar(65)` | A | CompileError@L2 | Is comparator not in _CMP_OP -> explicit rejection, checked before any operand is lowered. |
| `ast_is_not` | `x = 1 ⏎ if x is not 1: ⏎     putchar(65)` | A | CompileError@L2 | IsNot -> same path. |
| `ast_in` | `x = 1 ⏎ if x in (1, 2): ⏎     putchar(65)` | A | CompileError@L2 | In -> caught before operand lowering, so the Tuple literal never gets a chance to also error; message names the comparator. |
| `ast_not_in` | `x = 1 ⏎ if x not in (1, 2): ⏎     putchar(65)` | A | CompileError@L2 | NotIn -> same path. |
| `ast_walrus` | `if (n := 5) > 0: ⏎     putchar(n)` | A | CompileError@L1 | NamedExpr -> generic 'unsupported expression'. |
| `ast_ternary_ifexp` | `x = 5 ⏎ y = 1 if x > 0 else 0 ⏎ putchar(65)` | A | CompileError@L2 | IfExp -> generic 'unsupported expression'. |
| `ast_subscript_read` | `a = 5 ⏎ x = a[0] ⏎ putchar(65)` | A | CompileError@L2 | Subscript -> generic 'unsupported expression'. |
| `ast_subscript_assign` | `a = 5 ⏎ a[0] = 1 ⏎ putchar(65)` | A | CompileError@L2 | Subscript assignment target -> explicit rejection. |
| `ast_slice` | `a = 5 ⏎ x = a[1:2] ⏎ putchar(65)` | A | CompileError@L2 | Slice inside Subscript -> same generic Subscript rejection. |
| `ast_attribute_read` | `import sys ⏎ putchar(sys.maxsize)` | A | CompileError@L1 | 'import' rejected first; this only reaches Attribute handling if import were legal. Left in the corpus to document ordering. |
| `ast_attribute_read_no_import` | `class Dummy: ⏎     pass ⏎ x = Dummy.attr ⏎ putchar(65)` | A | CompileError@L1 | class rejected first (same reasoning); genuine Attribute-only probe is ast_attribute_assign below. |
| `ast_attribute_assign` | `a = 5 ⏎ a.x = 1 ⏎ putchar(65)` | A | CompileError@L2 | Attribute assignment target -> explicit rejection. |
| `ast_yield_from` | `def gen(): ⏎     yield from range(3) ⏎ putchar(65)` | A | CompileError@L2 | YieldFrom -> generic 'unsupported expression'. |
| `ast_async_def` | `async def f(): ⏎     return 1 ⏎ putchar(65)` | A | CompileError@L1 | AsyncFunctionDef isn't ast.FunctionDef -> falls to module_body, then compile_stmt finds no _stmt_AsyncFunctionDef -> generic 'unsupported... |
| `ast_await` | `async def f(): ⏎     x = await g() ⏎     return x ⏎ putch...` | A | CompileError@L1 | Same AsyncFunctionDef path fires before Await is ever examined. |
| `ast_match_stmt` | `x = 1 ⏎ match x: ⏎     case 1: ⏎         putchar(65) ⏎   ...` | A | CompileError@L2 | Match -> generic 'unsupported statement'. |
| `ast_raise` | `raise ValueError('x') ⏎ putchar(65)` | A | CompileError@L1 | Raise -> generic 'unsupported statement'. |
| `ast_ellipsis` | `x = ... ⏎ putchar(65)` | A | CompileError@L1 | Ellipsis is ast.Constant(value=Ellipsis) in modern ast; falls through _const()'s bool/int/str/float checks to the generic 'unsupported co... |
| `ast_complex_literal` | `x = 3j ⏎ putchar(65)` | A | CompileError@L1 | complex Constant -> same generic 'unsupported constant' fallback. |
| `ast_type_alias` | `type IntList = int ⏎ putchar(65)` | A | CompileError@L1 | PEP 695 'type' statement (3.12+) -> TypeAlias node has no _stmt_ handler -> generic 'unsupported statement' (skipped automatically on int... |
| `ast_docstring_module` | `"""doc""" ⏎ putchar(65)` | D | OK (编译通过) | Module docstring -> explicitly skipped in compile(). |
| `ast_docstring_func` | `def f(): ⏎     '''doc''' ⏎     return 1 ⏎ putchar(f())` | D | OK (编译通过) | Function-level bare string Expr -> _stmt_Expr's Constant branch is a no-op, same as CPython (docstring, no side effect). |
| `ast_bare_int_stmt` | `5 ⏎ putchar(65)` | D | OK (编译通过) | Bare int literal statement -> _stmt_Expr's Constant branch, no-op, matches CPython (expression statement evaluated and discarded). |
| `ast_bare_name_stmt` | `x = 5 ⏎ x ⏎ putchar(65)` | D | OK (编译通过) | Bare Name expression statement -> lower(Name) returns the name, no code emitted, discarded; matches CPython's no-op semantics for a defin... |
| `sem_undefined_var_read_toplevel` | `putchar(never_assigned)` | B | OK (编译通过) | lower(Name) only calls check_var_name (identifier *shape* validation); it never checks the name is actually bound anywhere -- same root c... |
| `sem_undefined_var_read_func` | `def foo(): ⏎     return undefined_var ⏎ putchar(foo())` | B | OK (编译通过) | Same missing check as above, but py2c ITSELF silently accepts this (compile_python_to_c returns C source with no CompileError -- see actu... |
| `sem_stray_return_toplevel` | `return 5 ⏎ putchar(65)` | C | OK (编译通过) | 'return' outside a function is a SyntaxError in real CPython (raised by the bytecode compiler, not by ast.parse -- ast.parse('return 5') ... |
| `sem_unbound_augassign` | `x += 1 ⏎ putchar(x)` | C | OK (编译通过) | _stmt_AugAssign never checks that the target was previously bound -- _bind_target just declares it. Real CPython: NameError: name 'x' is ... |
| `sem_bare_annassign_then_read` | `x: int ⏎ putchar(x)` | C | OK (编译通过) | Bare annotation (`x: int`, no value) only *declares intent* in real Python -- it does not bind x. _stmt_AnnAssign's `node.value is None` ... |
| `sem_call_undefined_function` | `putchar(bar(1))` | A | CompileError@L1 | Call to a name not in self.functions -> explicit rejection. |
| `sem_call_undefined_function_no_call_paren` | `bar ⏎ putchar(65)` | D | OK (编译通过) | Bare Name 'bar' (not a call) -- same as ast_bare_name_stmt: no check, no emitted code, silently a no-op. Included to show the asymmetry: ... |
| `sem_wrong_argcount_too_few` | `def f(a, b): ⏎     return a + b ⏎ putchar(f(1))` | A | CompileError@L3 | Argument count mismatch -> explicit rejection with counts in the message. |
| `sem_wrong_argcount_too_many` | `def f(a, b): ⏎     return a + b ⏎ putchar(f(1, 2, 3))` | A | CompileError@L3 | Same check, too many. |
| `sem_duplicate_function` | `def f(): ⏎     return 1 ⏎ def f(): ⏎     return 2 ⏎ putch...` | A | CompileError@L3 | Second registration of the same name -> explicit rejection. |
| `sem_function_case_collision` | `def foo(): ⏎     return 1 ⏎ def FOO(): ⏎     return 2 ⏎ p...` | A | CompileError@L3 | Upper-cased collision -> explicit rejection, names both functions. |
| `sem_function_case_collision_partial` | `def zAp(): ⏎     return 1 ⏎ def Zap(): ⏎     return 2 ⏎ p...` | A | CompileError@L3 | Same check with mixed-case names that upper-case identically. |
| `sem_zz_prefix_var_lower` | `zzx = 5 ⏎ putchar(zzx)` | A | CompileError@L1 | Reserved zz-prefix -> explicit rejection. |
| `sem_zz_prefix_var_upper` | `ZZfoo = 5 ⏎ putchar(ZZfoo)` | A | CompileError@L1 | check is name.lower().startswith('zz') -> case-insensitive, catches ZZ/Zz/zZ too. |
| `sem_zz_prefix_mixed` | `zZbar = 5 ⏎ putchar(zZbar)` | A | CompileError@L1 | Mixed-case zz prefix. |
| `sem_var_named_main` | `main = 5 ⏎ putchar(main)` | A | CompileError@L1 | 'main' is in C_KEYWORDS -> explicit rejection. |
| `sem_var_named_putchar` | `putchar = 5 ⏎ putchar(putchar)` | A | CompileError@L1 | 'putchar' is in C_KEYWORDS -> explicit rejection (fires on the assignment target before the call is even reached). |
| `sem_var_named_getchar` | `getchar = 5 ⏎ putchar(getchar)` | A | CompileError@L1 | 'getchar' is in C_KEYWORDS. |
| `sem_func_named_main` | `def main(): ⏎     return 1 ⏎ putchar(65)` | A | CompileError@L1 | 'main' is in C_KEYWORDS, so check_func_name's check_var_name() call catches it before the RESERVED_FUNCS check is ever reached -> message... |
| `sem_func_named_main_case_variant` | `def Main(): ⏎     return 1 ⏎ putchar(65)` | A | CompileError@L1 | Case variant 'Main' is NOT in C_KEYWORDS (exact-match, case-sensitive) so it reaches check_func_name's RESERVED_FUNCS check, which IS cas... |
| `sem_func_named_putchar` | `def putchar(x): ⏎     return x ⏎ putchar(65)` | A | CompileError@L1 | Same pre-emption as sem_func_named_main: 'putchar' is in C_KEYWORDS, caught there first. |
| `sem_func_named_getchar` | `def getchar(): ⏎     return 1 ⏎ putchar(65)` | A | CompileError@L1 | Same pre-emption for 'getchar'. |
| `sem_func_named_range_shadow` | `def range(x): ⏎     return x + 1 ⏎ putchar(range(65))` | B | CompileError@L3 | 'range' is not in RESERVED_FUNCS/C_KEYWORDS, so defining a function named 'range' is *accepted* at registration -- but _call() dispatches... |
| `sem_func_named_print_shadow` | `def print(x): ⏎     return x ⏎ putchar(print(65))` | B | CompileError@L3 | Same shadowing defect for 'print' (also not reserved at registration time). |
| `sem_func_named_ord_shadow` | `def ord(x): ⏎     return x ⏎ putchar(ord(65))` | B | CompileError@L3 | Same shadowing defect for 'ord': the user function registers fine, but every call is intercepted by the builtin ord() dispatch and fails ... |
| `sem_func_named_chr_shadow` | `def chr(x): ⏎     return x ⏎ putchar(chr(65))` | B | CompileError@L3 | Same shadowing defect for 'chr'. |
| `sem_func_global_name_collision` | `def foo(): ⏎     return 1 ⏎ foo = 5 ⏎ putchar(foo)` | D | OK (编译通过) | Function 'foo' and a later module-level variable 'foo' are both accepted; empirically verified this is a FALSE ALARM for a defect -- c2mg... |
| `sem_return_missing_path` | `def f(x): ⏎     if x > 0: ⏎         return 1 ⏎ putchar(f(5))` | D | OK (编译通过) | Function with a conditional return and no fallthrough return -- compiles; C leaves the return value of the fallthrough path unspecified (... |
| `sem_keyword_arg_call` | `def f(a, b): ⏎     return a + b ⏎ putchar(f(a=1, b=2))` | A | CompileError@L3 | keywords on a user call -> explicit rejection. |
| `sem_range_zero_args` | `for i in range(): ⏎     putchar(65)` | A | CompileError@L1 | range() arg count check. |
| `sem_range_four_args` | `for i in range(1, 2, 3, 4): ⏎     putchar(65)` | A | CompileError@L1 | range() arg count check. |
| `sem_range_kwargs` | `for i in range(stop=3): ⏎     putchar(65)` | A | CompileError@L1 | range() keywords -> explicit rejection. |
| `sem_range_var_step` | `n = 2 ⏎ for i in range(0, 10, n): ⏎     putchar(65)` | A | CompileError@L2 | Non-literal step -> explicit rejection. |
| `sem_break_in_loop` | `x = 1 ⏎ while x: ⏎     putchar(65) ⏎     break` | A | CompileError@L4 | break -> unconditionally rejected, even in an otherwise-legal loop (matches doc: 'the target backend has no break/continue'). |
| `sem_continue_in_loop` | `for i in range(3): ⏎     continue ⏎     putchar(65)` | A | CompileError@L2 | continue -> unconditionally rejected. |
| `sem_getchar_with_args` | `putchar(getchar(1))` | A | CompileError@L1 | getchar() arity check. |
| `sem_putchar_zero_args` | `putchar()` | A | CompileError@L1 | putchar() arity check. |
| `sem_putchar_two_args` | `putchar(65, 66)` | A | CompileError@L1 | putchar() arity check. |
| `sem_putchar_as_value` | `x = putchar(65) ⏎ putchar(66)` | A | CompileError@L1 | putchar() used in an expression context (not a bare Expr stmt) -> explicit rejection. |
| `sem_ord_non_literal_arg` | `x = 65 ⏎ putchar(ord(x))` | A | CompileError@L2 | ord() argument must be a literal (compile-time folded), not a variable -> explicit rejection naming the compile-time-evaluation requirement. |
| `sem_ord_multichar` | `putchar(ord('AB'))` | A | CompileError@L1 | ord() with len != 1 -> explicit rejection naming the value. |
| `sem_ord_empty_string` | `putchar(ord(''))` | A | CompileError@L1 | ord('') -> same len-check path (0 != 1). |
| `sem_chr_call` | `putchar(chr(65))` | A | CompileError@L1 | chr() -> explicit rejection. |
| `sem_print_call` | `print(65)` | A | CompileError@L1 | print() -> explicit rejection. |
| `sem_true_division` | `x = 10 ⏎ putchar(x / 2)` | A | CompileError@L2 | '/' -> explicit rejection naming '//' as the fix. |
| `sem_true_division_augassign` | `x = 10 ⏎ x /= 2 ⏎ putchar(65)` | A | CompileError@L2 | '/=' -> explicit rejection. |
| `sem_division_by_zero_const` | `putchar(5 // 0)` | A | CompileError@L1 | Constant-folded division by zero -> explicit rejection (distinct from the runtime zzdiv/zzmod helper, which returns 0 instead of trapping). |
| `sem_modulo_by_zero_const` | `putchar(5 % 0)` | A | CompileError@L1 | Same for modulo. |
| `sem_global_outside_function` | `global x ⏎ x = 1 ⏎ putchar(x)` | D | OK (编译通过) | 'global' at true module level: CPython treats this as a syntactically legal (if pointless) no-op, not a SyntaxError -- ast.parse and comp... |
| `sem_global_shadows_param` | `x = 1 ⏎ def foo(x): ⏎     global x ⏎     return x ⏎ putch...` | C | OK (编译通过) | In real CPython, `global x` naming a parameter is a SyntaxError at compile time ("name 'x' is parameter and global"). py2c's _stmt_Global... |
| `bnd_mod_minus_1` | `putchar(3486784400)` | D | OK (编译通过) | 3**20 - 1 is the largest representable ring value; folds unchanged. |
| `bnd_mod_exact` | `x = 3486784401 ⏎ putchar(x % 100 + 30)` | D | OK (编译通过) | 3**20 exactly wraps to 0 under the mod-3**20 fold (v % MOD in _const). |
| `bnd_mod_plus_1` | `x = 3486784402 ⏎ putchar(x % 100 + 30)` | D | OK (编译通过) | 3**20 + 1 wraps to 1. |
| `bnd_huge_literal` | `x = 10000000000000000000000000000000000000000000000000000...` | D | OK (编译通过) | A 100-digit literal -- Python ints are bignums so this is just an expensive-looking but correct '% MOD' fold; no overflow anywhere in the... |
| `bnd_empty_function_body_pass` | `def f(): ⏎     pass ⏎ putchar(f())` | D | OK (编译通过) | Empty body via explicit 'pass'; f() implicitly returns 0 (see sem_return_missing_path note) -- accepted either way. |
| `bnd_empty_source` | `` | D | OK (编译通过) | Empty file -> module_body is [] -> synthesized main() body becomes [ast.Pass()] (the 'or [ast.Pass()]' fallback) -> compiles to a no-op m... |
| `bnd_only_comment` | `# just a comment` | D | OK (编译通过) | Comment-only file -> tree.body is empty after parsing -> same Pass-fallback path as bnd_empty_source. |
| `bnd_only_whitespace` | `` | D | OK (编译通过) | Whitespace-only file -> same as above. |
| `bnd_only_docstring` | `"""just a docstring, no code"""` | D | OK (编译通过) | Sole statement is the module docstring, explicitly skipped in compile() -> module_body stays empty -> Pass fallback. |
| `id_nonascii` | `変数 = 5 ⏎ putchar(変数)` | A | CompileError@L1 | Unicode identifier is valid Python 3 syntax but fails the ascii() check in check_var_name. |
| `id_leading_underscore` | `_x = 5 ⏎ putchar(_x)` | A | CompileError@L1 | Leading underscore fails name[0].isalpha(). |
| `id_single_underscore` | `_ = 5 ⏎ putchar(_)` | A | CompileError@L1 | Single underscore, same isalpha() check on the first (only) char. |
| `id_python_keyword_class` | `class = 5 ⏎ putchar(65)` | A | CompileError@L1 | 'class' is a Python keyword -> SyntaxError at ast.parse, wrapped as a CompileError with 'Python syntax error' message. |
| `id_print_as_varname` | `print = 5 ⏎ putchar(print)` | D | OK (编译通过) | 'print' is not in C_KEYWORDS -- legal as a plain variable name as long as it's never *called* (calling it hits the builtin dispatch, see ... |
| `id_c_keyword_int` | `int = 5 ⏎ putchar(int)` | A | CompileError@L1 | 'int' is in C_KEYWORDS. |
| `id_c_keyword_while` | `while_ = 5 ⏎ putchar(while_)` | D | OK (编译通过) | Trailing underscore avoids the exact-match C_KEYWORDS check ('while_' != 'while') -- legal. |
| `ctrl_chained_comparison` | `x = 5 ⏎ if 0 < x < 10: ⏎     putchar(65)` | D | OK (编译通过) | Chained comparison desugars to (0<x) && (x<10); documented behaviour. |
| `ctrl_and_or_shortcircuit` | `x = 5 ⏎ if x > 0 and x < 10: ⏎     putchar(65) ⏎ if x < 0...` | D | OK (编译通过) | and/or -> nested if/else short-circuit lowering; documented. |
| `ctrl_not_operator` | `x = 0 ⏎ if not x: ⏎     putchar(65)` | D | OK (编译通过) | 'not' on a condition -> _materialize_cond handles UnaryOp(Not). |
| `ctrl_augassign_all_ops` | `x = 10 ⏎ x += 1 ⏎ x -= 1 ⏎ x *= 2 ⏎ x //= 2 ⏎ x %= 3 ⏎ pu...` | D | OK (编译通过) | All five supported augmented-assignment operators on a properly-initialised variable. |
| `ctrl_multi_target_assign` | `a = b = c = 65 ⏎ putchar(a) ⏎ putchar(b) ⏎ putchar(c)` | D | OK (编译通过) | a = b = c = expr -> computed once into 'a', copied to 'b'/'c'; documented multi-target assignment support. |
<!-- AUDIT_TABLE_END -->
