# 高级语言 → Malbolge 可行性调研

> 调研"把高级语言(如 Python)编译到 HeLL/Malbolge"的已有工作与落地路线。
> 2026-07-20。结论:可行,且名古屋大学已有先例栈可复用,推荐目标为 Malbolge20。

## 1. 已有工作全景(按抽象层)

### 名古屋大学栈(目标:Malbolge20,MIT 许可)

Iizawa 2005 年 99-bottles 论文的后继工作,持续到 2017 年,是**唯一做到
"C 风格语言 → Malbolge"的公开工作**:

| 层 | 语言/工具 | 状态 |
|---|---|---|
| C 子集(含递归调用) | `highlevel`(C 子集 → 伪指令) | **源码公开,MIT**(2026-07 经 GitLab API 发现的未链接仓库,见 §1.1);能力超出 2017 论文:+/-、全部比较、布尔、++/--、+=/-=、递归、数组;缺乘除 |
| 伪指令语言(.mg) | `ternary`(伪指令 → LAL 翻译器) | **源码公开,MIT**;支持 DEF/CALL/RETURN、IF/ELSE、SWITCH/CASE、REPEAT/BREAK/INF、GOTO、VAR、数组(IND_OPR)、INPUT/OUTPUT |
| LAL(低级汇编,.mc) | `lowass`(LAL → Malbolge20) | **源码公开,MIT**(perl 两阶段 + C++ init) |
| Malbolge20 运行时 | 参考解释器(C,分块懒初始化) | **源码公开,MIT**;pyMalbolge 已对齐并通过 conformance(hello20.mb) |

仓库:`git.trs.css.i.nagoya-u.ac.jp/malbolge/{highlevel,highlevel-examples,ternary,lowass,malbolge20-interpreter}`
(本地克隆在 `ref/nagoya-*/`,已 gitignore)。

### 1.1 修正与后续调查结论(2026-07-20)

- **C 前端源码其实是公开的**:GitLab group `malbolge` 下共 5 个仓库,其中
  `highlevel`(C 子集 → .mg)与 `highlevel-examples` 未被项目主页链接,
  仅能通过 GitLab API 发现。本文此前"前端源码未公开"的结论作废。
- `highlevel` 在 2017 论文之后继续演进:减法、全套比较运算符、布尔运算、
  复合赋值均已实现(论文"今後の課題"被部分做掉),2018-03 岩金(Iwagane)
  加入数组实现(无对应论文)。仅乘法/除法仍缺。
- **端到端实证**:`highlevel-examples/while.c`(while + 比较 + ++)经
  highlevel → ternary → lowass 编译为 5.8MB 的 .mb,pyMalbolge 3.6 秒输出
  `abcde`,与参考 C 解释器逐字节一致——四级管线今天即可用。
- 研究线活跃度:代码活动止于 2021-01,论文止于 2017-08,主页长期
  "under construction";酒井本人仍活跃但研究方向已转移。判定为休眠,
  无接棒团队。
项目页:https://www.trs.css.i.nagoya-u.ac.jp/projects/Malbolge/
(2010–2017 年间有约 8 篇 IEICE 技术报告,日文,PDF 可下载)。

### HeLL/LMAO 谱系(目标:原版 Malbolge + Unshackled,GPL-3)

- HeLL + LMAO(原版)、LMFAO(Unshackled):汇编器层,无高级语言前端。
- MalbolgeLISP(Kamila Szewczyk,2020-21):350MB 的 LISP 解释器,**手写**
  HeLL 方言(密码分析式方法),不是编译器产物。
- 详见 `docs/hell-spec.md`、`docs/lmao-internals.md`、`docs/hell-assembler-design.md`。

### 结论修正

此前判断"高级语言前端是空白"不准确:名古屋做过 C 子集编译器。真正的空白是:
**(a)** C 前端源码未公开(只有论文);**(b)** 没有任何 Python 前端;
**(c)** 名古屋栈缺少现代、活跃的运行时配套——这恰是 pyMalbolge 的位置。

## 2. 本次实证(pyMalbolge 已可作为名古屋栈的运行时)

- `hello20.mb`(名古屋 LAL 工具链产物)在 pyMalbolge 上运行:输出
  `HelloWorld`,46,417 步,0.6 秒,与参考 C 解释器一致(commit 57b7f10)。
- 为此修正了两处与参考实现的偏差:EOF 时 A=59049(非 3^20-1);
  SparseMemory 改为参考实现同款的分块懒初始化(逐 trit 种子跳跃表,
  我们从 crazy 表独立推导的跳跃表与其硬编码 num0/num1 表完全一致)。

## 3. 可行性判断

- **原版 Malbolge(59049 格)不适合作编译目标**:实测 LMAO 的 adder
  示例(仅十进制加法)已占 55.7K 格 ≈ 94% 内存。只够文本生成器玩。
- **Malbolge20 是正确的目标**:地址空间 3^20,名古屋栈证明了 C 子集
  (含递归)可编译落地;pyMalbolge 现在能跑其产物。
- **"真 Python"不可行,Python 子集可行**:对象/闭包/异常/bignum 超出
  合理工程量;整数变量、while/if、函数(递归)、一维数组、字符 I/O
  与伪指令层能力一一对应。
- **许可干净**:名古屋三仓库全部 MIT,无 LMAO 的 GPL 传染问题。

## 4. 推荐路线

```
Python 子集 (.py)
   │  ← 我们要写的唯一新组件(纯 Python)
   ▼
伪指令语言 (.mg)
   │  ternary(现成,MIT;后续可 Python 化)
   ▼
LAL (.mc)
   │  lowass(现成,MIT;后续可 Python 化)
   ▼
Malbolge20 (.mb)
   │  pyMalbolge(已就绪)
   ▼
运行 / 调试(TUI debugger 支持 --variant=malbolge20)
```

### 里程碑

- **P1 管线打通**:构建 ternary + lowass,跑通 `.mg → .mc → .mb → pyMalbolge`,
  样例进 `test/fixtures/`(伪指令层 conformance)。
- **P2 语言学习 + 前端**:精读 ternary 的语法文件与 2016/2017 论文(日文,
  需翻译),定义 Python 子集,写 `python → .mg` 编译器。
- **P3 端到端**:hello / 循环 / 递归 fib 从 Python 源码编译到 Malbolge20
  并在测试套里运行验证。
- **P4(可选)全栈 Python 化**:把 ternary/lowass 移植成 Python 模块
  (MIT,可直接移植),消除对 C++/perl/flex/bison 的构建依赖。

### 与 HeLL 汇编器计划的关系

`docs/hell-assembler-design.md` 的 LMAO 移植计划**保留但降级为备选**
(服务于原版 Malbolge 的研究价值);主线转向名古屋栈,理由:目标
(Malbolge20)内存充裕、许可干净、高层组件现成、且 pyMalbolge 在该
生态里有明确的独特定位(唯一的现代运行时 + 调试器)。

## 5. Python 前端(已实现 v1)

`malbolge/compiler/` 实现了本路线的最后一块:**Python 子集 → 名古屋高层
C 子集**的转译器。它没有直接生成 `.mg`,而是复用现成的
`ref/nagoya-highlevel/parser`(C → `.mg`),因此实际管线是:

```
Python 子集 (.py)
   │  ← malbolge/compiler(新组件,纯 Python,用标准库 ast)
   ▼
名古屋高层 C 子集 (.c)
   │  ref/nagoya-highlevel/parser
   ▼
伪指令 (.mg) → LAL (.mc) → Malbolge20 (.mb)   (scripts/mg2mb.sh)
   ▼
pyMalbolge 运行 / 调试
```

### 用法

```bash
# 只转译成 C(-  输出到 stdout)
python3 -m malbolge compile prog.py --emit-c prog.c

# 走完整管线生成可运行的 .mb(需要构建好 ref/ 工具链)
python3 -m malbolge compile prog.py -o prog.mb --seed 1
python3 -m malbolge --variant=malbolge20 prog.mb
```

```python
from malbolge.compiler import compile_python_to_c
c_source = compile_python_to_c("putchar(72)\nputchar(105)\n")
```

### 支持的 Python 子集

- 整数变量、赋值、`a = b = expr` 多目标赋值;增强赋值 `+= -= *= //= %=`。
- `if / elif / else`;`while`(含 `while x:` 真值判断);
  `for i in range(n) / range(a,b) / range(a,b,step)`(step 为正整数字面量,
  desugar 成 while)。
- 函数 `def`(位置参数、`return`、递归);`global` 声明写全局变量。
- 算术 `+ - * // %`;比较 `== != < > <= >=`(含链式 `a < b < c`);
  布尔 `and / or / not`(短路)。
- 内建:`putchar(x)`、`getchar()`、`ord('c')`(编译期折叠)。
- 常量表达式在编译期按 mod 3^20 折叠(如 `9 * 7 + 2` → `65`)。

### 明确的能力边界(友好报错,带行号与源码片段)

- **无负数**:一元负号 / 负字面量拒绝(值环 mod 3^20 无负数,`3 - 5` 折叠
  成大正数,`x < 0` 恒假)。
- **无真除法**:`/` 与 `/=` 拒绝,提示改用 `//`。
- **无 break / continue**(目标 C 子集没有;需改写循环条件)。
- 不支持:`chr`、`print`、字符串 / f-string、浮点、列表 / 字典 / 集合、
  类、`import`、`lambda`、推导式、嵌套函数、tuple 解包赋值、关键字实参。
- 标识符须以字母开头且非 ASCII 会拒绝;`zz` 前缀保留给编译器内部;
  与 C 关键字(`int`/`while`/`main`/`putchar`/…)同名的变量拒绝;函数名
  在后端会被转大写,同名(忽略大小写)冲突会拒绝。

### 实现要点(为何这样设计)

后端 C 子集有几个经实测确认的坑,转译器据此规避:

- **无运算符优先级**:`a < b && c` 会解析成 `a < (b && c)`。因此所有表达式
  一律降为三地址式(每条语句至多一个二元运算,操作数是裸变量或字面量)。
- **`bool` / `true` / `false` 损坏**:内部常量与 `TRUE_VAL/FALSE_VAL` 同值
  且被登记为 `INT`,常量缓存按值命名,导致布尔字面量类型错乱、向 bool
  变量赋值报 "Type mismatch"。因此**从不发射 `bool`/`true`/`false`**,布尔
  值一律用 `int` 0/1 经控制流物化(`flag = 0; if(cond){ flag = 1; }`,
  再 `while(flag != 0)` / `if(flag != 0)`)。
- **无 `* / %` 运算符**:按需注入 C 子集库函数 `zzmul`(倍增 double-and-add,
  约 32 次加法)、`zzdiv` / `zzmod`(长除),仅在真正用到时发射;除零返回 0
  以避免死循环。这些库函数的算法已用纯 Python 移植做穷举回归验证
  (见 `test/test_py2c.py::TestHelperAlgorithms`)。
- **标识符须字母开头**、**局部声明须在语句之前**、**声明只能用字面量初始化**:
  故所有局部 / 临时变量提前声明,初始化全部用运行期赋值;模块级变量声明成
  顶层全局(便于函数读取),其初值在生成的 `main()` 里赋。

### 测试

- `test/test_py2c.py`:纯转译单测(不依赖 ref 工具)——发射结构、常量折叠、
  临时变量展开、库函数注入、报错用例、库函数算法回归。
- `test/test_py2c_e2e.py`:两层,均在 ref 工具缺失时自动 skip——
  parser 接受层(生成的 C 通过 `ref/nagoya-highlevel/parser`)与全管线端到端
  层(Python → `.mb` 后运行并断言输出)。端到端断言优先用 **C 参考解释器**
  (`ref/nagoya-malbolge20-interpreter/malbolge20`,比 pyMalbolge 快 15–100 倍),
  并在 hi / echo 两个小用例上额外用 pyMalbolge 交叉验证输出一致。

### 已知取舍

- 运行时 `zzmul` / `zzdiv` / `zzmod` 正确但在 Malbolge20 上代价高(单个乘法
  的 `.mb` 可达 ~100MB、运行数分钟)。**能编译期折叠的常量乘除模不产生运行时
  开销**;因此 e2e 的乘法用例走常量折叠,运行时库函数的正确性由上述纯 Python
  穷举回归保证。含用户函数的程序在该工具链里体积明显放大(单函数即可达
  ~50MB)。
- **上游递归代码生成 bug 及本前端如何规避**:手写 C 里同一表达式**内联两次
  递归 CALL**(经典 `return fib(n-1) + fib(n-2)`)时,highlevel 生成的代码从
  fib(4) 起结果错误(fib(4) 得 2 应为 3;第二次 CALL 未保住栈上第一次的中间
  结果);pyMalbolge 与官方 C 参考解释器结果一致,确认是**上游编译器**问题。
  **本前端不受影响**:由于"无运算符优先级"本就要求把每个表达式降为三地址式,
  转译器绝不生成内联的双 CALL,而是发射 `t0 = f(a); t1 = f(b); r = t0 + t1;`。
  实测(C 参考解释器)该形式结果**正确**:Python 经典双递归 `fib(n-1)+fib(n-2)`
  编译后 fib(4)=3、fib(5)=5 均正确。即三地址拆分顺带绕开了上游这个 bug。
