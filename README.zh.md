# pyMalbolge

> [English](README.md) | **中文**

**用 Python 写,编译成能跑的 [Malbolge](https://en.wikipedia.org/wiki/Malbolge) 程序。**

pyMalbolge 是一个纯 Python 实现的编译器,把 Python 的一个子集编译到
[Malbolge20](https://www.trs.cm.is.nagoya-u.ac.jp/projects/Malbolge/),并附带
两个 Malbolge 变体的解释器和一个功能完整的调试器。不需要 C++、flex、bison 或
Perl 这些构建依赖 —— `pip install malbolge`,整条工具链就都在了。

[Fibonacci 示例](examples/fib.py)使用普通 Python 输入输出与内联双重递归。
十进制转换由编译器生成：

```python
def fib(n):
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)


n = int(input())
if 0 <= n <= 47:
    print(fib(n))
else:
    print("error")
```

编译一次后即可输入下标（换行或 EOF 结束输入）：

```console
$ uv run python -m malbolge compile examples/fib.py --backend=direct -o fib.mb
$ printf '10\n' | uv run python -m malbolge --variant=malbolge20 fib.mb
55
```

新产物已通过有限资源的项目 Python CLI 完成输入 `0`；优化 C 参考解释器也验证了
输入 `20` → `6765`。保留 v2 产物另在采样 RSS 低于 1 GiB 时完成，见[运行时实测](#运行时-qos2026-10-08)。

算术范围是 `0..47`，但双重递归的耗时呈指数增长。演示宜用 `6`、`7` 或 `10`
这样的小输入；在 Malbolge20 解释器上计算较大的下标并不实用。

Malbolge 由 Ben Olmstead 在 1998 年设计,目标是让一门语言尽可能地无法编程:每条
指令都是自修改的,操作码取决于指令自身的地址,算术是一个作用在三进制位上的查表
"crazy" 运算。第一个 Malbolge 程序不是写出来的,而是在语言问世两年后被集束搜索
*找到*的。本项目关心的是这段历史的另一端 —— 把普通代码编译进去。

- **编译器** —— Python 子集 → Malbolge20,两个相互独立的后端,输出完全确定
- **解释器** —— 原版 Malbolge(10 个三进制位(trit))和 Malbolge20(20 个 trit,稀疏内存)
- **调试器** —— 断点、观察点、回退单步、内存查看、反汇编;CLI 与 TUI 两种界面
- **已验证** —— 工具链移植与参考 C++/Perl 工具逐字节一致;一致性与端到端测试
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
# 默认自动 O3 编译并运行
uv run python -m malbolge compile examples/hello.py -o hello.mb
uv run python -m malbolge --variant=malbolge20 hello.mb

# 直连后端:跳过 C 这一层,在含控制流或函数的程序上输出体积大约减半,
# 并原生支持双重递归
uv run python -m malbolge compile examples/fib.py --backend=direct -o fib.mb

# 查看自动选择；显式关闭优化或缓存
uv run python -m malbolge compile examples/fib.py -o fib.mb --stats
uv run python -m malbolge compile examples/fib.py -O0 --no-cache -o fib.mb

# 导出各个中间阶段
uv run python -m malbolge compile prog.py --emit-c prog.c --emit-mg prog.mg --emit-mc prog.mc
```

编译默认 `-O3 --backend=auto`：可选 IR 环境可用时比较 Direct 和已验收
Semantic 候选，经结构化目标传递生成最终 MB 更小的方案。显式后端、IR 前端
和目标管线选择始终优先。`-O0` 关闭可选变换；`--backend=c` 保留参考 C 前端
及其已有内建简化。详见[编译优化策略](docs/design/compiler-optimization.zh.md)。

O3 CLI 默认在源码目录的 `.cache/malbolge` 缓存阶段，每个缓存产物上限
64 MiB。`--no-cache` 关闭；`--cache-dir` 显式启用不限单个产物大小的缓存。
键包含内容、工具链、实际优化策略、代码风格及 Python 版本；损坏项重新构建。
编译前检查输出路径，包括源码、symlink/hardlink 与多输出碰撞。
写入使用原子替换，CLI 将最终 `.mb` 流式写出，避免保留完整中间字符串；文件/编码
失败给出简明诊断。

### Python API

```python
from malbolge.compiler import compile_python_to_mb
from malbolge import eval20

mb = compile_python_to_mb('print("Hello, world!")')                   # 默认自动 O3
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

接受：无符号 `int` 变量与算术（`+ - * // %`，按 `3**20` 取模）；条件、
循环及 `break`/`continue`；返回操作数的惰性 `and`/`or`、惰性链式比较、
条件表达式；保存实参值的函数/相互递归、简单关键字调用、固定长度平坦 tuple
赋值/交换、负字面量步长的 `range()`；字节 I/O 与 `ord()`；模块与函数内
`int(input([字面量提示语]))`；可混合无符号整数、字符串字面量及基本运行时
整数 f-string 的 `print()`，支持字面量 `sep=`/`end=`。

先保存较早的操作数与 RHS 值，再执行后续副作用；range 边界固定，遍历使用
隐藏迭代器。输入失败与动态除法/取余零除数逐层退栈，main 仅输出一次 `error`
并终止。可能返回 None 的函数可用于副作用调用，但结果作为标量使用会被拒绝。

拒绝并指向原源码位置：一般有符号整数（明确的 range 边界/步长字面量为例外）、
真除法、运行时字符串/对象、返回字符串的原始 `input()`、通用 `int(...)`、
f-string conversion/格式规格或 print 之外的 f-string、嵌套/任意 tuple
拆包、starred/默认参数、类、import、推导式与嵌套函数。无符号边界以及保守的
赋值/返回路径检查细节见规格。

[规范性说明文档](https://github.com/Aiaid/pyMalbolge/blob/master/docs/specs/python-subset-spec.md)
覆盖了受理的 AST 白名单、与 CPython 语义之间有记录的分歧,以及诊断契约。

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
| 文本输出 | 每个字符一次 `putchar` | `print()` 支持运行时无符号整数与静态字符串，按需注入十进制辅助函数 |
| 十进制输入 | 手写字符解析 | 模块与函数内 `int(input([字面量提示语]))`，有明确的无符号范围与错误语义 |
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

### 运行时 QoS（2026-10-08）

[最终验收报告](docs/notes/python-qos-validation.json)记录了新编译的
**285,466,345 字节** Fibonacci 产物及完整哈希。缓存冷编译墙钟耗时
**38.173 s**（CLI 指标 **37.974 s**）；热缓存重复编译为 **1.415 s**
墙钟（CLI **1.212 s**），产物逐字节一致。这是完整新编译，非最终阶段耗时。

| 新产物执行 | 整进程耗时 | 已验证结果 |
|---|---|---|
| 有限资源项目 Python CLI，`n=0` | 82.494 s | `0\n`，73,378,255 步，正常终止 |
| 优化 C 参考解释器，`n=12` | 20.193 s | `144\n` |
| 优化 C 参考解释器，`n=20` | 279.169 s | `6765\n` |

Python CLI 内部指标为 82.410 s；上表整进程墙钟还包含解释器启动。

为隔离运行时存储改动，同一份保留 v2 产物（**277,965,145 字节**，SHA-256
`8fb3450ddb660aaad5f15731f7ef96366b3d4189a96fdd7a65f00c56d7ac2969`）也在
M1 Pro / 32 GiB 上完成了输入 `0` 的对照：

| 保留 v2 产物的解释器 | 整进程耗时 | 采样峰值 RSS | 结果 |
|---|---|---|---|
| 项目 Python CLI | 111.076 s | 0.846 GiB | `0\n`，退出码 0，stderr 为空 |
| 优化 C 参考解释器 | 11.591 s | 1.086 GiB | `0\n`，退出码 0，stderr 为空 |

这两个保留产物进程受 4 GiB 阈值监控，均未达到阈值。紧凑不可变源码、类型化可变页与
COW 快照取代逐单元字典；初始化填充值冻结，执行、复制、reset 与观察一致；
调试历史使用 deque/输出长度增量。这些均为含加载/初始化的单次整进程样本。

同一份**保留 `.mc`** 的紧凑映射最终汇编/写出为 **35.853 s**，隔离测量峰值
**144.0 MiB**，逐字节复现 v2。比先前 31.875 s 流式阶段慢约 12.5%，但显著
降低内存。历史完整 v2 编译为 103.432 s（旧 `mc2mb` 为 103.073 s）；这些
阶段测量不能冒充更新前端后的完整编译耗时。另一个辅助函数体积样本中，
字面量 `x * 3` 的 MC 从 204,296 字节降为 32,223，**减少 84.2%**；不是
一般性加速比。

### QoS 修复前的运行时输入基线（2026-10-08）

在 Apple M1 Pro、32 GiB 内存、macOS 27.0、CPython 3.12.9 上，最终的普通
Python 示例经纯 Python `direct` 后端编译耗时 **103.43 s**，产物为
**277,965,145 字节**（约 278 MB，十进制）。优化的 C 参考解释器（`-O3`）
完成了以下单次整进程测量，包含程序加载与初始化：

| 输入 `n` | 0 | 6 | 7 | 10 | 12 | 16 | 20 |
|---|---|---|---|---|---|---|---|
| C 参考解释器耗时（s） | 11.430 | 11.562 | 12.073 | 13.921 | 18.044 | 51.507 | 276.136 |

其跨子进程累计 max RSS 约为 **1.085 GiB**，并非各输入独立的内存峰值。
同一 Python 源码直接由 CPython 执行，`n=10` 的五次整进程耗时中位数为
**0.019145 s**，包含解释器启动。

在这份 **QoS 修复前基线**中，项目 Python CLI 未完成执行：`n=0` 时，基准在 **44.498 s** 后因达到
4 GiB RSS 阈值而停止进程，采样峰值为 **4.212 GiB**（采样间隔导致超出
阈值），没有输出。这是资源阈值停止，不是超时或完成耗时，也不能据此断言
完成执行需要多少内存。当时逐源码单元的 Python 字典构成表示层瓶颈；上方
紧凑内存结果已取代该限制。原始测量数值保持不变，作为历史证据。

[QoS 修复前共享测量数据](docs/notes/fib-input-performance.json)保留样本、环境与验证输出。
上述结果使用 `direct` 后端。`c` 后端也通过了 `0`、`10` 和非法输入的原生执行验证；
其产物为 572,759,579 字节，编译耗时 283.06 s。

### 历史基线

以下为 M 系列 Mac、CPython 3.9 上的历史实测。`fib(6)` 一行使用原先的固定输入
递归源码，不包含当前 `examples/fib.py` 的运行时十进制读取与输出逻辑：

| 源码 | `.mb` 体积(`c`) | `.mb` 体积(`direct`) | 编译 | 运行 | 步数 |
|---|---|---|---|---|---|
| `print("Hello, world!")` | 3.47 MB | 3.47 MB | 1.8 s | 3.0 s | 735 K |
| `for i in range(3): putchar(65+i)` | 27.3 MB | 11.9 MB | 5.7 s | 9.5 s | 3.0 M |
| 固定输入递归 `fib(6)`（历史） | 110.5 MB | 56.8 MB | 28.2 s | 53.8 s | — |

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

### 与参考工具链的对比

把同一个 `print("Hello, world!")` —— 相同的 C 输入、相同的 `.mg` 与 `.mc` 中间产物
—— 分别过名古屋的工具和本项目的移植:

| 阶段 | 名古屋(C++ / bison / Perl) | pyMalbolge(纯 Python) |
|---|---|---|
| C 子集 → `.mg` | 0.028 s | <0.001 s |
| `.mg` → `.mc` | 0.030 s | 0.003 s |
| `.mc` → `.mb` | 3.49 s | 1.72 s |
| **合计** | **3.55 s** | **1.72 s** |

Python 移植端到端**快了约 2 倍**,但这不是关于 Python 快慢的结论。整条管线由汇编阶段
主导,而它内层的地址搜索在这里做了记忆化,上游没有 —— 正是这一处改动让该阶段从
约 40 s/MB 降到 0.5 s/MB。其余阶段都快到语言差距根本显现不出来。

两条工具链产出的字节数**完全相同,均为 3,467,473 字节**。其中约 69% 的字节不一样,
而它们全都是 padding:程序永远不会执行到的单元,上游用 `srand(time(NULL))` 填充,
本移植则确定性地填充。两个二进制行为完全一致,且各自都能在对方项目的解释器上正确运行。

参考实现真正占据压倒性优势的地方是执行。在同一个 `.mb` 上:

| 解释器 | 耗时 |
|---|---|
| 名古屋参考实现(C) | 0.16 s |
| pyMalbolge(CPython) | 3.07 s |

差距 **19 倍**。这也是端到端测试在 `ref/nagoya-malbolge20-interpreter` 可用时会优先
调用它的真实原因。如果你要跑的是大型编译产物而不是调试它们,用 C 解释器;
如果你想要断点、回退单步和内存视图,用这个。

## 运行 Malbolge 程序

```bash
uv run python -m malbolge hello.mal                        # 原版 Malbolge
uv run python -m malbolge --variant=malbolge20 program.mb  # Malbolge20
uv run python -m malbolge cat.mal -i "Hello World"         # 喂入 stdin
```

```python
from malbolge import eval, eval20

eval('''(=<`#9]~6ZY32Vx/4Rs+0No-&Jk)"Fh}|Bcy?`=*z]Kw%oG4UUS0/@-ejc(:'8dc''')
# 'Hello World!'

eval('''(=BA#9"=<;:3y7x54-21q/p-,+*)"!h%B0/.~P<<:(8&66#"!~}|{zyxwvugJ%''', "abc123")
# 'abc123'

eval20(malbolge20_source, input_data)
```

### 批处理执行限制与指标

```bash
uv run python -m malbolge --variant=malbolge20 program.mb --input '7' \
  --eof sentinel --max-steps 10000000 --max-output 1024 --stats
# 输入原始字节：
uv run python -m malbolge --variant=malbolge20 program.mb --input-file input.bin --stats
```

`--input` 使用 UTF-8，`--input-file` 提供原始字节。带限制或 `--stats` 时按
批处理执行：从上述选项或管道读取输入；TTY 无显式输入选项时提供空 EOF，
在交互 shell 中执行批处理请用 `--input`。`--eof sentinel|stop` 设置 EOF
策略。指标为 stderr 上的一个 JSON 对象，程序字节保留在 stdout。达到资源
预算退出码为 3，非法指令为 2，正常终止或输入耗尽为 0。普通无限制 CLI
调用保留流式行为。

### 有限资源的字节执行 API

```python
from malbolge import run20

result = run20(malbolge20_source, b"7\n", max_steps=10_000_000,
             max_output=1024, eof="sentinel")
print(result.output)       # bytes
print(result.to_dict())    # 计数、寄存器与停止原因
```

限制接受非负整数或 `None`；零表示真正的零预算。停止原因区分正常终止、非法
指令、输入耗尽、步数限制和输出限制；输出将超过上限前停止。新 API 将文本
显式编码为 UTF-8，输入消耗按字节计数。旧 `eval()` 保留文本/codepoint
输入与默认 EOF-stop 行为；新 API 默认使用对应变体的 EOF 哨兵。原版解释器
通过 `malbolge.run` 提供相同接口（与 `run20`、`RunResult` 一同导出）。

> **Malbolge20 不向后兼容。** 它的 `crazy()` 作用在 20 个 trit 上,产生的结果与
> 10-trit 的原版不同,所以为其中一个变体写的程序,在另一个上不会正确运行。

| | 原版 | Malbolge20 |
|---|---|---|
| 字长 | 10 trits | 20 trits |
| 内存 | 59,049 个单元 | 约 34.8 亿个单元 |
| 内存模型 | 稠密数组 | 不可变源码 + 类型化写时复制页 |

## 调试器

```bash
uv run python -m malbolge debug hello.mal                     # CLI,类 GDB
uv run python -m malbolge debug --tui hello.mal               # TUI(需要 textual)
uv run python -m malbolge debug --variant=malbolge20 prog.mb
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

- [python-subset-spec](https://github.com/Aiaid/pyMalbolge/blob/master/docs/specs/python-subset-spec.md) —— 受理的 Python 子集的规范性说明
- [py2mg-backend](https://github.com/Aiaid/pyMalbolge/blob/master/docs/design/py2mg-backend.md) —— `py → .mg` 直连后端的设计
- [highlevel-to-malbolge](https://github.com/Aiaid/pyMalbolge/blob/master/docs/design/highlevel-to-malbolge.md) —— 流水线为什么长这样
- [mg-spec](https://github.com/Aiaid/pyMalbolge/blob/master/docs/specs/mg-spec.md) —— `.mg` 伪指令语言,从 `ternary` 逆向而来
- [hell-spec](https://github.com/Aiaid/pyMalbolge/blob/master/docs/specs/hell-spec.md) / [lmao-internals](https://github.com/Aiaid/pyMalbolge/blob/master/docs/upstream/lmao-internals.md) —— HeLL 与 LMAO 汇编器的算法
- [perf-baseline](https://github.com/Aiaid/pyMalbolge/blob/master/docs/notes/perf-baseline.md) —— 历史性能剖析基线；当前测量见 QoS 报告
- [toolchain-guide](https://github.com/Aiaid/pyMalbolge/blob/master/docs/upstream/toolchain-guide.md) —— 构建参考工具,用于一致性工作

## 开发

```bash
uv sync --extra dev
uv run --no-sync pytest test/
uv run --no-sync pytest test/ -n 2
```

`ref/` 下的参考工具是可选的。存在时,端到端测试会走它们来提速并交叉检查结果;不存在
时,一切回退到纯 Python 流水线。

本地 QoS 验收还包含最终定向的 207 项测试（128 个 subtest），以及两个
编译后端在项目 VM 上的便携执行（2 项测试/2 个 subtest）。[历史审计快照](docs/notes/python-qos-audit.json)由[验收报告](docs/notes/python-qos-validation.json)
结案，不改写原反例证据。

[CI 配置](.github/workflows/qos.yml)覆盖 Python 3.8/3.12/3.13，并设单独的
便携语义作业。Python 3.8/3.13 已通过本地冒烟检查；截至 2026-10-08，工作流
尚未推送或在 GitHub 运行。

## 路线图

- [x] Malbolge20 变体支持(20 trits,稀疏内存)
- [x] 调试器(CLI + TUI,带回退单步)
- [x] 完整 Nagoya 工具链的纯 Python 移植,逐字节一致
- [x] Python 前端,以及一个 `py → .mg` 直连后端
- [x] 无符号十进制输入输出、基本 print f-string、平坦 tuple 交换与简单关键字调用
- [ ] 编译器 v2：有符号整数、一般运行时对象/字符串，以及通过 `IND_OPR` 支持数组
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

- 最初 fork 自 [Avantgarde95/pyMalbolge](https://github.com/Avantgarde95/pyMalbolge)。
  此后解释器已完全重写,不包含任何原始代码;沿用下来的只有 `.mal` 示例程序和
  `ref/` 下 Ben Olmstead 置于公有领域的参考解释器。

## 许可证

MIT。`test/fixtures/hell/` 下的 HeLL 夹具来自 GPL-3 的 LMAO 发行版,带有各自的
许可声明;它们仅用于一致性测试,不属于打包发布的内容。
