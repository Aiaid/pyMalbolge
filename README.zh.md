# pyMalbolge

> [English](README.md) | **中文**

**用 Python 写,编译成能跑的 [Malbolge](https://en.wikipedia.org/wiki/Malbolge) 程序。**

pyMalbolge 是一个纯 Python 实现的编译器,把 Python 的一个子集编译到
[Malbolge20](https://www.trs.cm.is.nagoya-u.ac.jp/projects/Malbolge/),并附带
两个 Malbolge 变体的解释器和一个功能完整的调试器。不需要 C++、flex、bison 或
Perl 这些构建依赖 —— `pip install malbolge`,整条工具链就都在了。

```python
def fib(n):
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)

putchar(48 + fib(6))
```

```console
$ python3 -m malbolge compile fib.py --backend=direct -o fib.mb
$ python3 -m malbolge --variant=malbolge20 fib.mb
8
```

Malbolge 由 Ben Olmstead 在 1998 年设计,目标是让一门语言尽可能地无法编程:每条
指令都是自修改的,操作码取决于指令自身的地址,算术是一个作用在三进制位上的查表
"crazy" 运算。第一个 Malbolge 程序不是写出来的,而是在语言问世两年后被集束搜索
*找到*的。本项目关心的是这段历史的另一端 —— 把普通代码编译进去。

- **编译器** —— Python 子集 → Malbolge20,两个相互独立的后端,输出完全确定
- **解释器** —— 原版 Malbolge(10 个三进制位(trit))和 Malbolge20(20 个 trit,稀疏内存)
- **调试器** —— 断点、观察点、回退单步、内存查看、反汇编;CLI 与 TUI 两种界面
- **已验证** —— 工具链移植与参考 C++/Perl 工具逐字节一致;441 个测试
- **零运行时依赖** —— 只有想用 TUI 调试器时才需要 `textual`

## 安装

```bash
pip install malbolge          # 编译器 + 解释器 + CLI 调试器
pip install malbolge[tui]     # 追加 TUI 调试器(textual)
```

需要 Python 3.8+。

## 把 Python 编译到 Malbolge20

### 命令行

```bash
# 编译并运行
python3 -m malbolge compile examples/hello.py -o hello.mb
python3 -m malbolge --variant=malbolge20 hello.mb

# 直连后端:跳过 C 这一层,在含控制流或函数的程序上输出体积大约减半,
# 并原生支持双重递归
python3 -m malbolge compile examples/fib.py --backend=direct -o fib.mb

# 导出各个中间阶段
python3 -m malbolge compile prog.py --emit-c prog.c --emit-mg prog.mg --emit-mc prog.mc
```

### Python API

```python
from malbolge.compiler import compile_python_to_mb
from malbolge import eval20

mb = compile_python_to_mb('print("Hello, world!")')                   # 'c' 后端
mb = compile_python_to_mb('print("Hello, world!")', backend="direct") # 直连后端
print(eval20(mb))                                                     # Hello, world!

# 每个阶段都单独暴露出来:
from malbolge.compiler import (
    compile_python_to_c,    # Python subset -> Nagoya C subset
    compile_python_to_mg,   # Python subset -> .mg          (direct backend)
    translate_mg_to_mc,     # .mg -> .mc (LAL)              (port of nagoya-ternary)
    assemble_mc_to_mb,      # .mc -> .mb (Malbolge20)       (port of nagoya-lowass)
)
```

### 支持的 Python 子集(v1)

接受:`int` 变量与算术(`+ - * // %`,按 3^20 取模做常量折叠)、`while` / `if` /
`elif` / `else`、`for i in range(...)`、`break` / `continue`、链式比较、短路的
`and` / `or` / `not`、条件表达式(`a if c else b`,惰性求值)、函数定义与调用
(含相互递归)、`global`、`putchar()` / `getchar()` I/O、`ord()`,以及参数为编译期
常量的 `print()`(字符串字面量、常量整数、全常量 f-string、`sep=` / `end=`)。
文档字符串会被容忍。

拒绝,并给出带行号的 `CompileError`:负字面量与一元负号(值环是无符号的 mod
3^20)、真除法、运行期取值的 `print()` 参数、`chr`、运行期字符串与 f-string、
浮点数、`bool`、列表 / 字典 / 集合、类、`import`、`lambda`、推导式、嵌套函数、
元组解包与关键字参数。

[规范性说明文档](https://github.com/Aiaid/pyMalbolge/blob/master/docs/python-subset-spec.md)
覆盖了受理的 AST 白名单、与 CPython 语义之间全部十七处有记录的分歧,以及诊断契约。

## 流水线如何工作

```
             py2c                c2mg            mg2mc            mc2mb
Python  ──────────► Nagoya C ──────────► .mg ──────────► .mc ──────────► .mb
subset      │        subset             pseudo-        LAL low-      Malbolge20
            │                            instrs         level asm
            └──────────────────────────►
                  py2mg (direct backend)
```

| 阶段 | 是什么 |
|---|---|
| `py2c` | **我们自己写的。** Python AST → Nagoya C 子集。把一切降级为三地址式,绕开下游 C 编译器的若干缺陷,并注入 `zzmul` / `zzdiv` / `zzmod` 库例程,因为该 C 子集没有 `*`、`/` 和 `%`。 |
| `py2mg` | **我们自己写的。** Python AST → 直接生成 `.mg`,跳过 C 这一层。复用了已验证的代码生成原语,但替换了栈帧策略:按函数分配临时量、真正的递归环检测,以及只保护跨调用存活的那些临时量。 |
| `c2mg` | `nagoya-highlevel`(C 子集 → 伪指令)的纯 Python 移植,连 bug 一起复现,以保证输出与参考实现逐字节一致。 |
| `mg2mc` | `nagoya-ternary`(伪指令 → LAL)的纯 Python 移植。 |
| `mc2mb` | `nagoya-lowass`(LAL → Malbolge20)的纯 Python 移植,取代了原来两阶段的 Perl + C++ 实现。填充是确定性的,而不是以时间作种子。 |

每个移植都在一个夹具语料库上与原始工具逐字节比对,两个前端还做了端到端交叉检查:
同一份源码经两个后端编译,必须产生完全相同的*程序输出*。

### 与 Nagoya 工具链的对比

|  | Nagoya 工具链 | pyMalbolge |
|---|---|---|
| 实现 | C++ / flex / bison / Perl | 纯 Python |
| 获取方式 | 本地从源码构建 | `pip install malbolge` |
| 源语言 | C 子集 | Python 子集(C 子集这条路径作为其中一个后端保留) |
| `*` `/` `%` | C 子集里没有 | 常量折叠,或生成为库例程 |
| `for` 循环 | 只有 `while` | `for i in range(...)`,脱糖为 `while` |
| `break` / `continue` | 没有 | 标志降级,在嵌套循环中也正确 |
| 链式比较、短路 `and`/`or` | — | 支持 |
| 条件表达式 | — | `a if c else b`,惰性求值 |
| 文本输出 | 每个字符一次 `putchar` | 参数为常量的 `print()`,降级为一串 putchar |
| 诊断 | 解析器报错 | 带行号的 `CompileError`,附源码摘录 |
| 内联双重递归(`f(n-1) + f(n-2)`) | 从 fib(4) 起就编译错误 | 两个后端上都正确 |
| 输出确定性 | `srand(time(NULL))` 填充 —— 每次编译刻意都不一样 | 逐字节可复现 |
| 后端 | 一个 | 两个;直连的那个把输出体积大致减半 |
| 运行时 | 参考 C 解释器 | 两个变体的解释器,外加一个调试器 |
| 上游最后一次提交 | 2021 | 处于活跃维护 |

混淆在上游是一项设计目标 —— 伪指令层*本就应该*每次生成不同的东西。用它换来确定性,
才使得可复现构建和逐字节一致性测试成为可能;这也是本项目唯一一处刻意偏离原始行为、
而不是照原样复现的地方。

## 性能

Malbolge20 没有通常意义上的指令。光是加法就是一个在三进制位上跑二十步的循环,每个
单元在被执行后都会重写自己,而控制流则承载在一个寄存器里。因此编译出来的程序相对
源码而言*大得惊人*,而且跑得慢 —— 这是目标语言本身固有的,不是这个实现造成的。

在 M 系列 Mac、CPython 3.9 上实测:

| 源码 | `.mb` 体积(`c`) | `.mb` 体积(`direct`) | 编译 | 运行 | 步数 |
|---|---|---|---|---|---|
| `print("Hello, world!")` | 3.47 MB | 3.47 MB | 1.8 s | 3.0 s | 735 K |
| `for i in range(3): putchar(65+i)` | 27.3 MB | 11.9 MB | 5.7 s | 9.5 s | 3.0 M |
| 递归 `fib(6)` | 110.5 MB | 56.8 MB | 28.2 s | 53.8 s | — |

**输出体积。** 直连后端对直线代码没有帮助 —— 两个 `hello` 构建相差不到 1 KB ——
但对任何带控制流或函数调用的代码,体积大致减半。体积由调用点和循环决定,而不是由
输入的数值大小决定:典型情况是约 91 KB 的引导代码,加上每个 `putchar` 调用点几百 KB。

**编译**耗时由最后的汇编阶段主导,它的速度大约是**每 MB 输出 0.5 s**,并且基本与
输出体积成线性关系。一开始并非如此:`mc2mb` 里的地址搜索在递归时没有做记忆化,使得
汇编呈超线性、约 40 s/MB,把几 MB 的程序变成了要跑几分钟的构建。把这个搜索按
`(d, pos, depth)` 做缓存后,**快了约 100 倍,且输出逐字节一致**。

**执行**在 CPython 下大约是**每秒 240,000–320,000 条指令**,这是端到端实测,包含启动
和解析 `.mb` 的时间。调试器还要再慢 2–2.4 倍,因为回退单步需要记录执行历史。
墙钟时间随递归深度呈超线性增长,尽管 `.mb` 体积并非
如此 —— 深递归会触及更多地址空间,而稀疏内存是随用随惰性物化的。

实际上:小程序没问题,任何带真正递归的程序都是对耐心的考验。两者都在预期之中。

## 运行 Malbolge 程序

```bash
python3 -m malbolge hello.mal                        # 原版 Malbolge
python3 -m malbolge --variant=malbolge20 program.mb  # Malbolge20
python3 -m malbolge cat.mal -i "Hello World"         # 喂入 stdin
```

```python
from malbolge import eval, eval20

eval('''(=<`#9]~6ZY32Vx/4Rs+0No-&Jk)"Fh}|Bcy?`=*z]Kw%oG4UUS0/@-ejc(:'8dc''')
# 'Hello World!'

eval('''(=BA#9"=<;:3y7x54-21q/p-,+*)"!h%B0/.~P<<:(8&66#"!~}|{zyxwvugJ%''', "abc123")
# 'abc123'

eval20(malbolge20_source, input_data)
```

> **Malbolge20 不向后兼容。** 它的 `crazy()` 作用在 20 个 trit 上,产生的结果与
> 10-trit 的原版不同,所以为其中一个变体写的程序,在另一个上不会正确运行。

| | 原版 | Malbolge20 |
|---|---|---|
| 字长 | 10 trits | 20 trits |
| 内存 | 59,049 个单元 | 约 34.8 亿个单元 |
| 内存模型 | 稠密数组 | 稀疏、惰性物化 |

## 调试器

```bash
python3 -m malbolge debug hello.mal                     # CLI,类 GDB
python3 -m malbolge debug --tui hello.mal               # TUI(需要 textual)
python3 -m malbolge debug --variant=malbolge20 prog.mb
```

```
(maldbg) break 10       # Set breakpoint at address 10
(maldbg) run            # Run until breakpoint
(maldbg) step 5         # Step 5 instructions
(maldbg) back 2         # Step back 2 instructions
(maldbg) examine 0 20   # Examine memory at address 0
(maldbg) disassemble    # Show disassembly
(maldbg) registers      # Show register values
```

![TUI Debugger Screenshot](https://raw.githubusercontent.com/Aiaid/pyMalbolge/master/screenshots/tui.png)

TUI 按键:`↓` 单步,`↑` 回退单步,`r` 运行,`b` 切换断点,
`←`/`→` 滚动内存,`0` 重新居中到 D,`h`/`?` 帮助,`q` 退出。

```python
from malbolge import MalbolgeDebugger
from malbolge.core import MalbolgeConfig

dbg = MalbolgeDebugger(source, input_data, config=MalbolgeConfig.malbolge20())
dbg.add_breakpoint(10)
state = dbg.step()       # one instruction
state = dbg.step_back()  # undo it
state = dbg.run()        # until the next breakpoint
print(dbg.registers, dbg.output)
print(dbg.disassemble(0, 10))
```

## Malbolge 全景

Malbolge 编程基本上沿着两条彼此独立的线发展,而本项目位于第二条线的末端。

**搜索,然后手工汇编(原版 Malbolge)。** 多年来程序是被*生成*出来的,而不是写出来
的:Andrew Cooke 在 2000 年的 hello world 出自一次集束搜索;Lou Scheffer 的密码分析
—— 它找到了加密表中的 2-cycle,并证明了系统化编程根本上是可能的 —— 至今仍是其他
一切工作的基础。由于原版变体只有 59,049 个内存单元,对
[zb3/malbolge-tools](https://github.com/zb3/malbolge-tools) 这类生成器来说,打印
固定文本仍是实际能力的上限。Matthias Lutter 的 **HeLL** 汇编语言及其 **LMAO** 汇编器
(GPL-3)把这条线提升到了可以手写的程度,而 **LMFAO** 面向的是
[Malbolge Unshackled](https://esolangs.org/wiki/Malbolge_Unshackled) —— Ørjan
Johansen 提出的图灵完备、内存无界的变体。现存最复杂的 Malbolge 程序,Kamila
Szewczyk 的 **MalbolgeLISP** —— 一个约 350 MB 的 LISP 解释器 —— 就是用那个方言
手写的。

**编译(Malbolge20)。** 名古屋大学从另一个方向研究了这个问题大约十年,发表了关于
图灵完备性、SAT 辅助合成三进制位级运算,以及代码分配判定过程的论文,并在 2013 年
提出了 **Malbolge20**:一个 20-trit 的变体,更大的字长和地址空间让真正的编译器成为
可能。他们的工具链(MIT 许可)是一个三阶段的下降过程 —— 一个 C 子集编译到一种伪指令
语言,再降级到 LAL 低级汇编器,最后汇编成 Malbolge20。值得注意的是,伪指令这一层
把*混淆当作一个特性*:同样的输入,每次编译都应当产生不同的输出。

**本项目补上了什么。** Nagoya 那套栈是 C++/flex/bison/Perl 写的,需要本地构建;最后
一次提交停在 2021 年。pyMalbolge 用纯 Python 重新实现了全部三个阶段,与原版逐字节
比对验证,并在其上放了一个 Python 前端 —— 包括上游 C 子集所没有的 `*`、`//` 和 `%`,
外加 `for` 循环、链式比较、短路布尔运算和带行号的诊断。直连后端则完全绕开了 C 这一层。
输出被做成确定性的而非混淆的,这正是可复现构建和逐字节一致性测试得以成立的前提。
除此之外,它还是一个持续维护的、面向两个变体的现代运行时,并配有一个真正的调试器。

## 文档

设计笔记和逆向得到的语言规范都放在
[`docs/`](https://github.com/Aiaid/pyMalbolge/blob/master/docs/README.md)。
每份文档都有英文(`<name>.md`)和中文(`<name>.zh.md`)两个版本。

- [python-subset-spec](https://github.com/Aiaid/pyMalbolge/blob/master/docs/python-subset-spec.md) —— 受理的 Python 子集的规范性说明
- [py2mg-backend](https://github.com/Aiaid/pyMalbolge/blob/master/docs/py2mg-backend.md) —— `py → .mg` 直连后端的设计
- [highlevel-to-malbolge](https://github.com/Aiaid/pyMalbolge/blob/master/docs/highlevel-to-malbolge.md) —— 流水线为什么长这样
- [mg-spec](https://github.com/Aiaid/pyMalbolge/blob/master/docs/mg-spec.md) —— `.mg` 伪指令语言,从 `ternary` 逆向而来
- [hell-spec](https://github.com/Aiaid/pyMalbolge/blob/master/docs/hell-spec.md) / [lmao-internals](https://github.com/Aiaid/pyMalbolge/blob/master/docs/lmao-internals.md) —— HeLL 与 LMAO 汇编器的算法
- [perf-baseline](https://github.com/Aiaid/pyMalbolge/blob/master/docs/perf-baseline.md) —— 性能剖析,以及被修掉的两个热点
- [toolchain-guide](https://github.com/Aiaid/pyMalbolge/blob/master/docs/toolchain-guide.md) —— 构建参考工具,用于一致性工作

## 开发

```bash
pip install -e .[dev]
python3 -m pytest test/           # 441 tests
python3 -m pytest test/ -n auto   # ~2.6x faster with pytest-xdist
```

`ref/` 下的参考工具是可选的。存在时,端到端测试会走它们来提速并交叉检查结果;不存在
时,一切回退到纯 Python 流水线。

## 路线图

- [x] Malbolge20 变体支持(20 trits,稀疏内存)
- [x] 调试器(CLI + TUI,带回退单步)
- [x] 完整 Nagoya 工具链的纯 Python 移植,逐字节一致
- [x] Python 前端,以及一个 `py → .mg` 直连后端
- [ ] 编译器 v2:有符号整数、十进制 `print()` / `input()`、通过 `IND_OPR` 支持数组和字符串
- [ ] Malbolge Unshackled 支持(3-adic 整数、可变旋转宽度、Unicode I/O)

## 参考资料

**语言本身**

- [Malbolge — Esolang](https://esolangs.org/wiki/Malbolge) · [Wikipedia](https://en.wikipedia.org/wiki/Malbolge)
- [Malbolge Unshackled — Esolang](https://esolangs.org/wiki/Malbolge_Unshackled) —— 图灵完备的变体
- Lou Scheffer,[Introduction to Malbolge](http://www.lscheffer.com/malbolge.shtml) —— 让编程成为可能的那次密码分析

**Malbolge20 与 Nagoya 工具链**(MIT)

- [项目主页](https://www.trs.cm.is.nagoya-u.ac.jp/projects/Malbolge/) —— 论文、在线汇编器和解释器
- [工具链源码](https://git.trs.css.i.nagoya-u.ac.jp/malbolge) —— `highlevel`(C 子集 → `.mg`)、`ternary`(`.mg` → LAL)、`lowass`(LAL → Malbolge20),以及参考解释器。此处镜像在 `ref/` 下,仅用于一致性测试。
- Kato et al. (2013), *Malbolge with 20trits word length and its programming support tool*, IEICE —— 提出 Malbolge20
- Kanbe et al. (2016), *An intermediate language for a compiler generating highly obfuscated Malbolge codes*, IEICE SS2016 —— `.mg` 这一层
- Sakanashi et al. (2017), *A compiler that translates to Malbolge from a C-language subset containing recursive calls*, IEICE SS2017-18 —— C 前端

**HeLL / LMAO 这条线**(GPL-3)

- [lutter.cc/malbolge](https://lutter.cc/malbolge/) —— HeLL、LMAO、LMFAO、HeLL-IDE 及在线工具
- [MalbolgeLISP](https://github.com/kspalaiologos/malbolge-lisp) —— 一个跑在 Malbolge Unshackled 上的 LISP 解释器

**生成器**

- [zb3/malbolge-tools](https://github.com/zb3/malbolge-tools) —— 三种生成策略,外加一个 web GUI
- [lutter.cc/unshackled](https://lutter.cc/unshackled/) —— Unshackled 参考实现

**本项目**

- Fork 自 [Avantgarde95/pyMalbolge](https://github.com/Avantgarde95/pyMalbolge)

## 许可证

MIT。`test/fixtures/hell/` 下的 HeLL 夹具来自 GPL-3 的 LMAO 发行版,带有各自的
许可声明;它们仅用于一致性测试,不属于打包发布的内容。
