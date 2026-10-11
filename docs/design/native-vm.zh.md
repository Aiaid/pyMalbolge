# 可选原生 Malbolge20 VM

> [English](native-vm.md) | **中文**
>
> 状态：本地扩展原型，Malbolge20 批处理默认优先使用可用的原生 VM，
> 不可用时回退 Python。JIT 仍需显式启用。
> 本文描述执行层；编译器 lowering 与目标映像生成独立。

下方首次验收是带日期的纯原生快照，记录时 Python 仍为默认引擎。
后续可选[带守卫 JIT](native-jit.zh.md)
增加独立引擎；原有源码指纹与测量作为历史证据保留，不代表当前二进制。

Python 包可以保留常规 API，同时把一整批指令放入 C 扩展执行。原生边界
覆盖指令分派、寄存器、稀疏内存、自修改、字节输入输出和执行预算。
每条指令不会回调 Python 内存方法。

## 构建与使用

在有 C 编译器和当前解释器 Python 头文件的源码工作副本中运行：

```sh
uv run --with setuptools --with wheel python scripts/build_native_vm.py
```

二进制针对 `uv` 选中的 Python 构建；切换解释器 ABI 后需要重新构建。
构建适配器使用 macOS、Linux、Windows 标准编译器发现；当前本地验收为
macOS ARM64。源码安装可以自动构建新原生 wheel。工作副本二进制仍由 Git
忽略且不进入源码包；原生 wheel 只纳入全新暂存构建的扩展。构建模式、
安装产物检查及待运行的托管 CI 矩阵见[原生打包](native-packaging.zh.md)。

```python
from malbolge import run20

result = run20(code, input_data=b"7\n", max_steps=10_000_000,
               max_output=4096, eof="sentinel", engine="native")
print(result.output)
print(result.stop_reason, result.steps)
```

`run20` 默认 `engine="auto"`：优先使用原生 VM，扩展不可用时回退 Python。
`engine="python"`、`engine="native"` 和 `engine="jit"` 显式选择引擎。
显式选择不可用的原生/JIT 引擎会抛出错误并给出构建/平台提示。
导入或执行时不会构建扩展，`auto` 也不会启用 JIT。安装时的构建行为由
独立的 `MALBOLGE_NATIVE_BUILD` 控制。

Malbolge20 CLI 批处理采用相同默认值，包括无限制的管道和重定向 stdin。
使用 `--engine auto|python|native|jit` 选择：

```sh
uv run python -m malbolge --variant=malbolge20 program.mb --input '7' --stats
uv run python -m malbolge --variant=malbolge20 program.mb --engine python --input '7'
```

`--stats` 报告实际 `engine` 与 `requested_engine`。stdin 连接 TTY 且无
批处理选项时保留 Python 流式交互；从 TTY 显式选择原生/JIT 时，必须提供
`--input` 或 `--input-file`。`eval20` 的旧字符 API、原版变体及调试器继续
使用 Python。

默认选择的验收单独记录于
[原生引擎选择](../notes/native-engine-selection-validation.json)：220 项定向
测试、一个条件跳过及六个 subtest 通过，并包含真实默认 CLI 运行。
下方历史吞吐测量未重新运行。

## 执行与内存契约

原生执行返回与 `core.run_memory` 相同的 `RunResult`。它保持字节消耗、文本
输入的 UTF-8 转换、EOF 值 59049、sentinel/stop 策略、指令前预算检查、HALT
步数计入、未知有效 opcode 的空操作，以及跳转后对当前 C 地址的加密。
ROT/CRZ 写入 D=C 时，随后的加密检查会读取写入结果。

原生内存保留已分离的不可变源码和冻结的周期默认值。读取不物化页面；写入
创建 4096 单元 uint32 页面，快照共享页面直至写入。源码之外唯一写入的计数
保持 Python 的分配计数含义。支持字节与 uint32 宽字源码；外部写入限于
uint32，任意 Python 整数内存仍由 `SparseMemory` 提供。执行变体为 Malbolge20。

首个原型保留 GIL，每执行 16,384 条指令检查 Python 信号。运行中的内存对象
拒绝信号回调里的重入执行、修改、复制和重新初始化。释放 GIL 以及接入调试器
单步/历史记录是后续独立改动。

预初始化内存 API 明确划分计时边界：

```python
from malbolge.core import MalbolgeConfig, parse_source
from malbolge.native import NativeMemory, run_memory

memory = NativeMemory(parse_source(code, MalbolgeConfig.malbolge20()))
result = run_memory(memory, b"7\n", max_steps=10_000_000)
pages = memory.export_pages()  # 分离的页面值与写入标记，供核对使用
```

每次执行均把寄存器置零，与 `core.run_memory` 一致；内存保留写入。这一 API
不宣称支持断点续跑。

## 正确性与测量

```sh
uv run --no-sync pytest test/test_native_vm.py test/test_runtime_qos.py -q
uv run --no-sync python scripts/benchmark_native_vm.py \
  --output-dir /tmp/native-vm-comparison --repeats 5
```

测试对照 Python 实现核对结果、指令边界停止、页面内容、写入标记、分配计数、
初始化默认值和快照隔离。真实 MB 夹具另覆盖独立 C 参考。测速先验收输出、输入、
HALT、步数和寄存器契约，再让独立新进程串行运行同一映像与输入。

执行计时排除文件读取、验证和提前初始化；执行中自然产生的页面分配计入。
Python/原生结果构造计入；参考 C 的最终 stdout flush 位于执行时钟之外。
C 计时副本只在原样执行函数调用前后读时钟；独立插桩正确性门禁不提供测速
数据。合成 NOP/自修改控制项与既有夹具分开。共享机器上的 CPU/墙钟分布
属于探索性证据，不代表编译器或映像体积优化。

### 本地验收，2026-10-10

此历史快照早于 `auto` 默认值；当时默认 Python，原生执行需显式选择。
以下测量保持原样。

[验证清单](../notes/native-vm-validation.json)：105 项定向测试及 6 项 subtest
通过，独立 C 审查和 Clang 静态分析通过；Python 3.8.19 构建并通过三个夹具的
结果/页面/API 检查。wheel/sdist 检查确认排除了本地 ABI 二进制和私有研究。
这是本地原型验收，不宣称已重新运行完整测试集或云端 CI。

macOS arm64 / CPython 3.12.9，每个引擎五次新进程轮换样本：

| 同一 MB | Python CPU ms | 原生 CPU ms | 参考 C CPU ms | 原生相对 C 加速 |
|---|---:|---:|---:|---:|
| Hi | 61.213 | 0.694 | 2.466 | 3.55x |
| 字节回显 | 27.854 | 0.308 | 1.576 | 5.12x |
| 重复输出 | 82.946 | 0.899 | 3.087 | 3.43x |
| 函数调用 | 168.335 | 1.837 | 5.322 | 2.90x |
| 合成百万 NOP/自修改 | 652.489 | 6.641 | 4.298 | 0.65x |

三类正确性门禁与全部 75 条计时样本均验收通过；源码、映像和二进制指纹稳定。
这些小夹具证明原生核心有实际收益，不证明普遍加速；NOP 控制项也表明参考 C
的分派仍可能更快。

### 参考 C 与后续 JIT

参考 `mem_manage` 会重建十 trit 的局部地址；已检查的 `-O3` arm64 汇编仍保留
多次整数/浮点转换与乘加。其算术用两 trit 查表处理十组，新内存块填充 59,049
单元。新核心使用整数页寻址、四 trit 查表和冻结周期默认值。这些是已观察到的
实现差异；尚未用消融实验分离各项对速度的贡献。

首次纯原生验收时没有 JIT；后续 [NOP 块试验](native-jit.zh.md) 已提供显式
机器码路径。一般原生 trace 引擎可能减少重复分派、地址解析和寄存器中间
读写，但必须防护指令加密及通过 D 写入后续代码，保持精确步数/输出/输入边界，
守卫失败时安全退回解释执行。每条指令都粗粒度使整个页面失效，会抵消大部分
收益；感知自修改的 trace 需要更精细的设计。先建立优化解释器基线，再把翻译/
预热与稳定执行分开，才可把收益归因于 JIT。
