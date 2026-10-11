# 带守卫的原生 NOP 块 JIT

> [English](native-jit.md) | **中文**
>
> 状态：叠加在[原生 VM](native-vm.zh.md)上的显式 ARM64 试验。
> Malbolge20 批处理默认优先使用可用的原生解释器，否则回退 Python；
> JIT 不会自动选择。这是为 Malbolge 指令生成机器码，与 CPython 自身 JIT 独立。

## 构建与选择

```sh
uv run --with setuptools --with wheel python scripts/build_native_vm.py
```

```python
from malbolge import run20

result = run20(code, input_data=b"7\n", max_steps=10_000_000,
               max_output=4096, engine="jit")
```

CLI 用 `--engine jit` 选择此试验；从 TTY 执行时需提供 `--input` 或
`--input-file`：

```sh
uv run python -m malbolge --variant=malbolge20 program.mb --engine jit --input '7' --stats
```

`run20` 和 CLI 批处理默认 `auto`，选择原生或 Python，不启用 JIT。
`python` 与 `native` 也可显式选择。导入和执行时不构建扩展，源码安装可以
通过 [wheel hook](native-packaging.zh.md) 编译。
CLI `--stats` 包含实际 `engine` 与 `requested_engine`。

首个发射器支持小端 ARM64 macOS/Linux，本地实测目标为 macOS arm64。
ARM64e、大端 ARM64 和其他架构报告不可用。显式选择不可用的 JIT 会抛出错误；
JIT 引擎内部遇到不支持的目标操作时使用原生解释器。原型保留 GIL 与原生 VM
的信号/预算契约。

## 真实机器码与守卫

`_native_jit.h` 为 2、4、8、16、32、64 单元的标准 opcode 68 NOP 块生成
真正的 ARM64 LDR/CMP/条件分支/MOVZ/STR/RET 指令。每条目标 NOP 仍加密自己
的代码单元。守卫在每次存储之前检查当前 uint32 值；代码改变时返回精确的
已执行前缀，再正常解释第一条尚未执行的指令。此阶段的算术、间接寻址、跳转
和输入输出仍为标量解释。

调用受限于单个可写 COW 页、内存环绕、执行预算、16,384 步信号区间和计数器
范围。调用者仅为已完成单元记录写入标记及源码外唯一分配，寄存器和步数与
逐条解释一致。生成函数检查当前值，因此后续代码写入、源码重置及不同内存
对象不会依赖旧源码身份而绕过守卫。

进程缓存由 1 MiB 区域及 94 个地址余数乘六种块长度限制。机器码来自可信固定
模板；目标字节用于数据与守卫，不直接作为机器指令。macOS 使用 MAP_JIT、
线程写保护和指令缓存失效，Linux 使用 RW→RX 保护。不修改解释器签名或系统
安全设置；映射失败明确报告，信号回调后再次分派前检查可用状态，进程退出时
释放代码区域。

平台实现依据 [Apple JIT 指南](https://developer.apple.com/documentation/apple-silicon/porting-just-in-time-compilers-to-apple-silicon)
和 [pthread API 声明](https://github.com/apple-oss-distributions/libpthread/blob/main/include/pthread/pthread.h)。

## 指标与验证

```python
from malbolge.core import MalbolgeConfig, parse_source
from malbolge.native import NativeMemory, run_memory

memory = NativeMemory(parse_source(code, MalbolgeConfig.malbolge20()))
result = run_memory(memory, b"7\n", jit=True, max_steps=10_000_000)
print(memory.jit_stats())
```

末次执行统计提供实际 JIT 块/步数、标量步数、守卫退出、发射块/字节、发射
CPU/墙钟及当前进程缓存大小。`jit_steps + fallback_steps == result.steps`，
包含标量 HALT。可用性和统计查询不映射或生成代码；冷执行包含区域准备和
机器码发射，零预算执行不改变 VM 页面。

```sh
uv run --no-sync pytest test/test_native_jit.py test/test_native_vm.py -q
uv run --no-sync python scripts/benchmark_native_jit.py \
  --output-dir /tmp/native-jit-comparison --repeats 3
```

比较以相同映像/输入，在独立新进程中顺序运行 Python、原生、冷 JIT、热 JIT
及参考 C。所有模式必须匹配输出、输入消耗、HALT、步数/寄存器和完整
Python/原生/JIT 页面状态。记录实际机器码覆盖率，零覆盖耗时不宣称 JIT 加速。

一次完整遍历不一定能稳定块形状缓存。暖态 worker 有界地用全新内存逐轮
预热到某轮零发射，记录每轮及完整阶段成本，然后计时另一份新内存。验收的
热态样本不发射新代码；冷总耗时不扣除翻译成本，预热成本始终单独可见。
合成 NOP 控制项与既有编译程序夹具分开报告。

## 本地验收，2026-10-10

此历史快照记录时默认引擎为 Python。当前优先原生的 `auto` 默认值
不改变 JIT 需显式启用的状态，以下测量保持原样。

[验证清单](../notes/native-jit-validation.json)：160 项定向测试、一个平台条件
跳过、六项 subtest 通过。独立审查、Clang 分析、Python 3.8.19 的真实 JIT/
页面/API 检查及打包排除均通过。最终构建前加固了 Linux RX 恢复失败的分派
路径；该路径在 Darwin 上静态复审，没有在 Linux 上故障注入。

macOS arm64 / CPython 3.12.9，同映像五模式、新进程三轮轮换；下表是执行
CPU 毫秒中位数：

| 用例 | 原生 | 冷 JIT，包含发射 | 热 JIT | 参考 C | 热 JIT 覆盖率 |
|---|---:|---:|---:|---:|---:|
| Hi | 0.814 | 1.465 | 1.142 | 2.450 | 42.0% |
| 字节回显 | 0.376 | 0.804 | 0.523 | 1.575 | 41.7% |
| 重复输出 | 1.065 | 1.837 | 1.480 | 2.882 | 42.2% |
| 函数调用 | 2.200 | 3.555 | 3.241 | 5.325 | 41.2% |
| 合成百万 NOP/自修改 | 7.232 | 1.711 | 1.137 | 4.266 | 99.9999% |

控制项的冷/热总耗时比原生快 4.23x/6.36x，比参考 C 快 2.49x/3.75x。
其冷发射 CPU 为 0.087 ms，47 个模板共 84,600 代码字节，区域上限 1 MiB。
四个真实小夹具即使热态也回退约 39–47%，冷态同样慢于原生。本试验保留显式
启用，这些结果不支持改成默认。

全部 75 个计时样本及状态/页面门禁通过。暖态夹具缓存需要三轮新内存预热，
控制项需要两轮。预热执行 CPU 总量依次为 3.871/1.857/4.831/10.360/2.952 ms，
记录还保留包含准备和状态检查的整个预热阶段时钟。验收的热态样本零新发射。
较早的单轮预热矩阵被拒绝并单独保留；本轮协调采样在另一会话恢复未计时
initializer 之前完成。

## 后续

本试验尚不翻译一般控制流或算术。先用同映像测量判断短 NOP 守卫/形状提升
是否有收益，再扩展 trace 范围。混合 trace 需要明确的别名/副作用守卫及安全
解释器退出，并分别保留编译、预热、缓存大小和稳定执行证据。
