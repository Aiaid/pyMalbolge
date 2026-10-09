# 小型 Python 基准程序库

> **中文** | [English](README.md)

这组普通 Python 程序为 Python → C/MG → MC → Malbolge20 → VM 流水线提供可重复的
正确性与性能输入。源码使用正常的 `int(input())` 和 `print()`，可原样在 CPython
运行。这是一份小型测试库，不是通用 Python 一致性测试，也不代表已有速度结论。

在仓库根目录，先选择快速降低检查或最小 VM 基线：

```bash
uv run --no-sync python scripts/benchmark_pipeline.py \
  --manifest benchmarks/manifest.json --suite standard --stop-after mc
uv run --no-sync python scripts/benchmark_pipeline.py \
  --suite smoke
```

`manifest.json` 统一记录程序路径、固定 ASCII 输入、预期 ASCII 输出、执行预算及
测试分组。路径相对于清单文件。程序库共 **12 个程序、32 组输入**：

| 分组 | 程序数 | 输入组数 | 覆盖内容 |
| --- | ---: | ---: | --- |
| `smoke` | 2 | 2 | 字面量输出、常量算术折叠 |
| `standard` | 8 | 24 | 十进制回显、求和、分支、欧几里得 GCD、迭代 Fibonacci、阶乘、字面量及动态乘法 |
| `stress` | 2 | 6 | 双递归 Fibonacci、互递归 |

`smoke` 选择两个最小程序；`standard` 包含 smoke 和 standard 分组，共 10 个程序、
26 组输入；`all` 包含全部分组。每个需要输入的程序均有 `zero`、`small`、`medium`
三组输入。这些名称只表示同一个程序内部的相对输入规模，不表示不同程序工作量相同。

需要精确选择或独立 CPython 运行时：

```bash
# 按完整程序 ID 精确选择；比较时明确指定后端。
uv run --no-sync python scripts/benchmark_pipeline.py \
  --manifest benchmarks/manifest.json --cases fibonacci_iterative fibonacci_recursive \
  --backends direct --workloads small --runtime

# 直接用 CPython 运行单个源码。
printf '10\n' | uv run --no-sync python benchmarks/programs/fibonacci_iterative.py
```

执行器在每次编译采样中只编译每份选定源码一次，再用其产物运行该程序的全部选定
输入；每组输入使用新建的 VM 内存。重复次数、产物目录、后端及性能分析选项见
执行器的 `--help`。完整汇编和 VM 执行与快速降低检查分开；递归程序需要通过
`all` 或精确程序选择主动启用。完整套件可能生成较大的 MB 产物，每组输入还会
执行引导代码及十进制 I/O 辅助函数；成本可能远高于用 CPython 运行这些短源码。

输出为 `summary.csv`（每组输入一行）和 `report.json`（完整阶段指标与哈希）。
省略 `--output-dir` 时自动建立新临时目录并打印位置；需要命名保存时指定新目录。
不同输入行共享相同编译成本，不能将这些编译列跨输入累加。
`--workloads small` 只选小输入。默认采样一次；耗时对比可用 `--repeats 3`。
没有综合评分或耗时通过门槛，也未包含 SPEC 基准代码。

正常生成 MB 的运行默认同时 benchmark 三项：**冷编译耗时、最终 MB 产物大小、
产物运行耗时**。CSV 还保留阶段计时之和、VM 执行时间、精确步数和每秒步数。
`run_seconds` 包含产物读取、验证、初始化与执行，不含进程启动；完整进程
耗时在 JSON 中。速度主比较用固定输入的运行总耗时；每秒步数衡量 VM 吞吐，
会受指令混合影响。`--stop-after mc` 明确属于编译检查，没有最终产物或目标运行结果。

编译与运行还分别记录当前进程 CPU 时间，与墙钟时间区分。硬件/Python 信息、
前后负载/供电上下文保存在 JSON，不可用探针保持未知；上下文采集在计时区间外。
CPU 时间排除了调度等待，但仍受硬件、频率、温度和缓存影响，不是硬件归一化。
繁忙 Mac 上的单轮属于探索性基线；更严谨的 A/B 比较应在同机空闲条件下
交替重复采样。

现有 Python examples 另有 `examples.json` 清单，使用
`--manifest benchmarks/examples.json --suite all` 可选中三份源码。
六份原始 `.mal` examples 属于另一种机器变体，见 `examples/README.zh.md`。

## 测量边界

1. 先将每组输入与固定 CPython 输出比较，确认正确性。CPython 子进程基线包含
   解释器启动，应明确标注；输出校验所耗时间不能作为 VM 速度采样。
2. 分别测量 Python 前端（`c` 后端还包括 C → MG）、MG → MC、汇编与引导代码生成、
   MB 写出。记录源码及产物哈希、体积、后端、环境和重复次数。
3. 分开测量 MB 读取与校验、VM 内存初始化和执行。引导代码、十进制解析/格式化及
   程序本身都会产生执行成本；小输入可帮助观察这些固定成本。
4. 在相同环境下比较未开启性能分析的重复采样。性能分析和指令追踪有自身开销，
   应作为独立诊断采样。

运行时输入防止主要计算被折叠为常量，两个 smoke 程序则有意测量常量路径。
迭代和递归 Fibonacci 使用相同输入及输出。两种乘法使用相同数值操作数及输出，
但动态版本多读取一行，因此总执行时间包含额外的十进制解析；将差异归因于乘法
本身之前，应先分离这部分成本。

清单中的所有输入均满足 CPython 与 Malbolge20 一致的非负、无溢出整数语义
（`0 <= value < 3**20`）。阶乘最大为 `12!`，GCD 在求余前检查除数，递归减法在
基例检查之后执行。输出契约仅覆盖清单中的有效输入；任意负数、格式错误、缺失、
溢出或极大输入均不属于本库范围。步数与时间预算用于限制执行工作量，不是性能
验收阈值。本库没有硬编码的耗时门槛，也没有未经测量的提速声明。

## 验证

```bash
# 清单、全部 CPython/MG/MC，以及两个后端的最小真实 VM 样例。
uv run --no-sync pytest test/test_benchmark_corpus.py -q
```

前端/MC 接受源码并不能证明较大程序的运行时等价。要验证这些输入在当前编译器与
VM 上的 MB 执行结果，需要运行完整基准并启用运行时检查。
