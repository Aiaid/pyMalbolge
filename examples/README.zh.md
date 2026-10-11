# 示例

> **中文** | [English](README.md)

## 编译器的 Python 源码

| 文件 | 展示内容 | 输入 | 输出 |
|---|---|---|---|
| `hello.py` | 常量字符串 `print()` | 无 | `Hello, world!\n` |
| `countdown.py` | `for` / `range`、`break`、`continue`、`%`、`putchar()` | 无 | `ACE`（无换行） |
| `fib.py` | 双递归、十进制 `int(input())` 与整数 `print()` | `6\n` | `8\n` |

编译现默认 O3/auto，比较 Direct 与适用的 semantic 候选；显式 `c` 和
`direct` 后端均可将三个示例编译为 Malbolge20。
比较后端时使用不同的输出文件名：

```bash
uv run python -m malbolge compile examples/hello.py -o hello-auto.mb --stats
uv run python -m malbolge --variant=malbolge20 hello-auto.mb --input '' --stats

uv run python -m malbolge compile examples/hello.py --backend=c -o hello-c.mb
uv run python -m malbolge compile examples/hello.py --backend=direct -o hello-direct.mb
uv run python -m malbolge --variant=malbolge20 hello-direct.mb --input '' --max-steps 400000000 --max-output 4096 --stats

uv run python -m malbolge compile examples/countdown.py --backend=direct -o countdown.mb
uv run python -m malbolge --variant=malbolge20 countdown.mb --input '' --max-steps 400000000 --max-output 4096 --stats

printf '6\n' | uv run examples/fib.py  # CPython：8
uv run python -m malbolge compile examples/fib.py --backend=direct -o fib.mb
uv run python -m malbolge --variant=malbolge20 fib.mb --input '6' --max-steps 400000000 --max-output 4096 --stats
```

达到预算时命令返回退出码 3。`--stats` 将指标写入 stderr，程序输出保留在 stdout。
Malbolge20 批量执行默认可用时使用原生，否则 Python；`--stats` 标明实际
引擎。与下方旧 Python 测量比较时指定 `--engine=python`；JIT 需显式选择。
显式 `--input '6'` 在 EOF 处结束，十进制转换也接受 `6\n`。
旧源码注释可能仍展示历史命令或早期仅支持常量 `print()` 的限制；
当前子集也支持无符号整数十进制输出，见 [Python 子集规格](../docs/specs/python-subset-spec.zh.md)。

## 2026-10-08 性能工作后的历史比较

此快照采用显式后端和 Python VM，早于 O3/auto 与批处理优先原生的默认值。
这些体积与耗时不描述当前自动选择。

| 源码 | 后端 | MB 字节数 | 编译阶段总和，基线 → 当前（秒） | 当前 VM 总耗时（秒） | 执行步数 |
|---|---|---:|---:|---:|---:|
| `hello.py` | `c` | 3,467,473 | 0.468 → 0.424 | 0.666 | 736,373 |
| `hello.py` | `direct` | 3,466,627 | 0.484 → 0.648 | 0.670 | 735,114 |
| `countdown.py` | `c` | 159,275,293 | 21.339 → 18.682 | 53.333 | 58,129,606 |
| `countdown.py` | `direct` | 68,019,999 | 8.418 → 8.012 | 21.310 | 23,342,300 |
| `fib.py` | `c` | 590,717,433 | 85.153 → 67.112 | 169.320 | 180,551,521 |
| `fib.py` | `direct` | 285,466,345 | 38.008 → 32.505 | 79.654 | 85,110,921 |

六次 VM 运行均正常终止，输出与首表完全一致；Fibonacci 输入为 `6\n`。预算为每个进程 400,000,000 步、4,096 输出字节及 480 秒。编译耗时是独立阶段计时的总和，除 MB 写出外不包括诊断/产物写入；这样避免将早期子进程中为保存证据而重复的基线解析计入比较。相同 C 后端 Fibonacci 产物的独立原生 C 参考解释器核对也输出 `8\n`（退出码 0，stderr 为空）。

这是全新、无编译缓存的单次采样。编译器基线早于本轮性能工作，
但基线 VM 已采用与当前版本相同的分组三进制运算实现。
每个示例、每个后端的 `.mg`、`.mc`、`.data` 和 `.mb` SHA-256
在编译器修改前后均完全一致。运行时数据只对当前产物在当前项目 Python VM
各运行一次，因此不能据此声称旧、新 VM 的加速比。并行基准活动使小幅耗时差异较嘈杂。
解析/布局、引导代码生成和产物写出分别计时；总运行时间包括加载和校验。

Direct 后端产物大小分别为 C 后端 countdown 的 42.7%、Fibonacci 的 48.3%。本轮性能修改本身保持产物大小不变。

可用[基准运行器](../benchmarks/README.zh.md)重新测量现有示例的两个后端：

```bash
uv run python scripts/benchmark_pipeline.py --manifest benchmarks/examples.json --suite all --runtime --output-dir /private/tmp/pymalbolge-examples-new
```

独立的小型 Python 基准库覆盖更多算法和固定输入规模；`--suite smoke --runtime` 提供最小起步，`--suite all --stop-after mc` 可广泛检查降级阶段。

## Fibonacci 输入与实际范围

`fib.py` 读取 `n = int(input())`，检查 `0 <= n <= 47`，然后打印 `fib(n)`。
`fib(n - 1) + fib(n - 2)` 展示双递归。编译器负责十进制转换，
源码无需字节 I/O 辅助函数。

编译后的程序读取一行无符号 ASCII 十进制数，以 LF 或 EOF 结束，
接受可选前导 `+`、两侧 ASCII 空白、前导零及 CRLF；单独 CR 作为空白。
转换支持 `0..3486784400`；空输入、非法或溢出输入会输出 `error\n` 并结束主程序。
CPython 对非法转换或空 EOF 会抛出通常的异常；运行时字符串和 Python 异常不在编译器子集中。

源码对 `n > 47` 输出 `error\n`。`F(0) = 0`、`F(1) = 1`，
`F(47) = 2971215073` 可放入无符号字；`F(48)` 溢出。
输出为完整十进制数及换行，无输入提示。

双递归耗时呈指数增长。`0..47` 是算术范围；建议用 `6` 等小输入演示。
编译产物可能达到数百 MB，运行的大量步骤会先初始化生成的程序。

[QoS 验证报告](../docs/notes/python-qos-validation.json) 保留了此前存储、
缓存及原生参考解释器的测量，包括更大的 Fibonacci 输入。
[QoS 前报告](../docs/notes/fib-input-performance.json) 记录了被取代的 Python
内存表示在 4 GiB 阈值处停止的情况。这些是历史证据，与上表的新比较分开。
根目录 README 中早期固定输入 `fib(6)` 的数字也对应尚无运行时十进制转换的旧源码。

## 手写 Malbolge 程序（原始变体）

运行方式：`uv run python -m malbolge <file>`。
这些程序面向原始 Malbolge，并非 Malbolge20 编译产物。

- `hello.mal`：来自 https://en.wikipedia.org/wiki/Malbolge#Example_Program
- `cat.mal`：来自 https://esolangs.org/wiki/malbolge#Cat
- `quine.mal`：来自 http://matthias-ernst.eu/malbolgequine.html
- `99bottles.mal`：来自 http://www.99-bottles-of-beer.net/language-malbolge-995.html
- `truth.mal`：来自 https://esolangs.org/wiki/Truth-machine#Malbolge
- `cat2.mal`：来自 https://commons.wikimedia.org/wiki/File:Malbolge_cat_program.png
