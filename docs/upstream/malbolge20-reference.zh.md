# Malbolge20：机器模型与工具链分层

> [English](malbolge20-reference.md) | **中文**
>
> 核查日期：2026-10-27。本文是项目参考文档，不是新的语言规范。
> 下述机器细节以公开 C 解释器的上游版本
> `2b42f4817afecca6b4c4f7374e21a399b6488e31` 为依据；实现边界另行标明。

## 扩展改变了什么

Malbolge20 把 Malbolge 的字长和地址宽度从十个三进制位（trit）扩展为二十个。
[官方项目页](https://malbolge20.gitlab.io/index-en.html)列出了 2013 年的技术报告
*Malbolge with 20trits word length and its programming support tool*，作者为
Tatsuki Kato、Masahiko Sakai、Toshiki Sakabe、Keiichirou Kusakari 和 Naoki
Nishida。[名古屋大学机构库记录](https://nagoya.repo.nii.ac.jp/records/21421)给出
IEICE Technical Report 113(160)，73–78 页，2013 年 7 月，报告号为
SS2013-25 / KBSE2013-25。官方项目页却列为第 159 期；本文采用机构库记录的期号，
并明确保留这一差异，避免悄然混用引文。项目页还链接了解释器、汇编语言定义和
编译器源码。

| 属性 | 原版 Malbolge | Malbolge20 |
|---|---:|---:|
| 字和地址的 trit 数 | 10 | 20 |
| 可寻址单元数 | `3^10 = 59,049` | `3^20 = 3,486,784,401` |
| 字和地址的取值范围 | `0…59,048` | `0…3,486,784,400` |
| 右旋使用的乘数 | `3^9 = 19,683` | `3^19 = 1,162,261,467` |

这些数字表示逻辑单元数与值域，并不规定宿主分配大小、以 gigabit 表示的源文件大小，
或可用物理内存。参考解释器按需分块分配内存；这一分配策略实现的是固定地址空间，
并没有把它变为无界空间。见参考源码的 `main`、`mem_manage` 和 `increment`。
（[C 源码](https://gitlab.com/malbolge20/malbolge20_creator/-/blob/2b42f4817afecca6b4c4f7374e21a399b6488e31/runtime/malbolge20-interpreter/malbolge20.c)）

## 寄存器、源码载入与内存

代码与数据共用内存。三个寄存器是 `A`（累加器）、`C`（代码指针）和
`D`（数据指针），初值均为零。下文 `[x]` 表示地址 `x` 的内存内容；
寄存器赋值和内存写入是不同操作。

C 载入器跳过空白，把剩余源码字符的字符编码从地址零开始连续存入内存。
每个源码位置只接受可打印 ASCII 字符，且经过与位置有关的解码后必须对应八条具名
指令之一。因此，源码字符并不是与地址无关的固定操作码。其余内存按下式递推初始化：

```text
[i] = crazy([i-1], [i-2])
```

这里 `crazy(x, y)` 的参数顺序在下文定义。初始内容由载入程序决定，并非全部为零。
C 载入器拒绝少于两个非空白字符的输入，其诊断把这类输入称为空输入。
不能仅凭递推式推断单字符程序的行为。这些载入细节来自参考实现的 `main` 和
`make_init_mem`，并非来自编译器的中间语言。
（[C 源码](https://gitlab.com/malbolge20/malbolge20_creator/-/blob/2b42f4817afecca6b4c4f7374e21a399b6488e31/runtime/malbolge20-interpreter/malbolge20.c)）

## 解码与指令周期

C 参考实现先检查 `[C]` 是否在 `33…126` 范围内，再通过 `xlat1` 表得到规范化的
指令字符：

```text
xlat1[([C] - 33 + C) mod 94]
```

这里的 `C` 是完整地址，包含参考实现的块号。用等价余数 `([C] + C) mod 94`
可以得到下表。中间一列是解码后的字符，不一定是该源码位置实际写下的字符。

| 余数 | 解码字符 | 公共更新之前的效果 |
|---:|:---:|---|
| 4 | `i` | `C := [D]` |
| 5 | `<` | 在 C 参考实现中把累加器作为字节输出 |
| 23 | `/` | 将输入读入 `A` |
| 39 | `*` | `A := [D] := rotate([D])` |
| 40 | `j` | `D := [D]` |
| 62 | `p` | `A := [D] := crazy(A, [D])` |
| 68 | `o` | 空操作 |
| 81 | `v` | 立即停机 |

运行时，其他解码字符也执行空操作；在这些空操作形式中，载入器只接受指定的 `o`
作为源码中的空操作指令。
对于不停机的指令，参考实现随后把 **此时** `C` 所指单元通过其 94 字符替换表
`xlat2` 改写，再递增 `C` 和 `D`，按 `3^20` 回绕：

```text
[C] := xlat2[[C] - 33]
C := (C + 1) mod 3^20
D := (D + 1) mod 3^20
```

顺序会影响行为。跳转在替换前改变 `C`：被替换的是从 `[D]` 载入的地址所指单元，
下一条指令则从该地址加一处读取；通常并不是改写原来的跳转指令单元。
载入 `D` 后同样还要执行公共递增。这里的解码和替换机制与原版 Malbolge 相同；
加宽机器字并没有增加操作码或引入新的替换表。
（[参考实现的 `exec` 与查找表](https://gitlab.com/malbolge20/malbolge20_creator/-/blob/2b42f4817afecca6b4c4f7374e21a399b6488e31/runtime/malbolge20-interpreter/malbolge20.c)）

**实现边界：** C 参考实现在取指单元不是可打印 ASCII 时报告错误。但在跳转或内存
写入之后，它没有再次检查 `xlat2` 的索引。因此，该源码并未为所有可能的不可打印
替换目标定义安全行为。pyMalbolge 为后一次查表增加了保护；这是实现选择，不能据此
推断这些边界情况的统一语言规则。

## 三进制运算与兼容性

右旋把最低 trit 移到最高位：

```text
rotate(x) = x div 3 + (x mod 3) × 3^19
```

crazy 运算在二十个 trit 位置上分别查下表。行选择 **第二个** 参数 `y` 的 trit，
列选择 **第一个** 参数 `x` 的 trit。

| `crazy(x, y)` | `x = 0` | `x = 1` | `x = 2` |
|---|---:|---:|---:|
| `y = 0` | 1 | 0 | 0 |
| `y = 1` | 1 | 0 | 2 |
| `y = 2` | 2 | 2 | 1 |

该表不满足交换律。运算指令使用 `crazy(A, [D])`，初始化使用
`crazy(前一单元, 前二单元)`。C 实现的 `op(x, y)` 通过等价的 9×9 表每次处理两个
trit。
（[参考实现的 `op` 与旋转](https://gitlab.com/malbolge20/malbolge20_creator/-/blob/2b42f4817afecca6b4c4f7374e21a399b6488e31/runtime/malbolge20-interpreter/malbolge20.c)）

十 trit Malbolge 程序通常不能直接兼容 Malbolge20，即使源码能通过两个载入器。
例如，右旋 `1` 在十 trit 下得到 `19,683`，在二十 trit 下得到 `1,162,261,467`。
`crazy(0, 0)` 则产生全为 1 的机器字：十 trit 下为 `29,524`，二十 trit 下为
`1,743,392,200`。高位的零也参与运算。这些例子直接由旋转公式和 trit 表推导而来，
不是基准测试，也不意味着每一个程序的行为都会改变。

## 输入、输出与输入结束

C 参考实现使用 `getc` 读取，使用 `putc` 写出。在面向字节的 ASCII 系统上，
输出是 `A` 的低字节（`A mod 256`），输入字节直接成为 `A`。遇到 EOF 时，它赋值
**`59049 = 3^10`**，而不是二十 trit 全为 2 的值
`3^20 - 1 = 3,486,784,400`。源码还包含宿主换行适配。因此，应把 EOF 常量记录为
参考实现的行为，不能根据字宽猜测其值。
（[参考实现的输入输出分支](https://gitlab.com/malbolge20/malbolge20_creator/-/blob/2b42f4817afecca6b4c4f7374e21a399b6488e31/runtime/malbolge20-interpreter/malbolge20.c)）

pyMalbolge 面向字节的 `run20` API 和批处理 CLI 默认使用该哨兵值。
显式选项 `eof="stop"` 是宿主侧便利功能，在输入耗尽时停止执行。历史上返回字符串的
`eval20` API 默认采用这种便利行为，并接受以字符为单位的输入；它并不定义参考机器
的字节 I/O。见 [`malbolge20.py`](../../malbolge/malbolge20.py) 和
[`core.py`](../../malbolge/core.py)。

## 有界内存与 Malbolge Unshackled

二十 trit 带来了大得多的固定内存，但它仍然有限。内存单元数有限、每个单元的值域
有限、寄存器的值域有限，因此机器的内部配置总数也有限。不另加外部存储机制时，
这是有界存储机器，而不是拥有无界工作带的图灵完备机器。这个结论来自固定机器
模型，并不是关于 `3^20` 到底够不够大的悬而未决问题。

Malbolge Unshackled 是独立变体，其设计围绕无界寻址和可在执行过程中增长的旋转
宽度展开，并非仅将 Malbolge20 的固定常量换成更大的数。
[Unshackled 工具与参考页](https://lutter.cc/unshackled/)链接了语言规范和设计者的
参考解释器，并说明了可增长的旋转宽度。不能从 Malbolge20 的 C 解释器推断
Unshackled 的 Unicode I/O 或算术语义。

## 汇编与编译器分层

当前的[规范工具链 README](https://gitlab.com/malbolge20/malbolge20_creator/-/blob/2b42f4817afecca6b4c4f7374e21a399b6488e31/README.md)
描述了以下路线：

```text
类 C 源码（.c）
  → 带控制的伪指令序列（.mg）
  → 低级汇编语言 LAL（.mc）
  → 内存映像（.data）
  → 可执行的 Malbolge20 源码（.mb）
```

`highlevel` 提供类 C 前端；`ternary` 将 `.mg` 降低为 LAL；`lowass` 构造内存映像
与初始化程序；解释器执行最后的 `.mb`。
[官方 LAL 定义](https://malbolge20.gitlab.io/20trits_lal/lal-def-en.html)描述了标号、
单元、例程、标志和恢复指令，用于汇编自修改代码。这些构造属于汇编语言，并非
Malbolge20 新增的机器指令。

pyMalbolge 提供另一个从已记录的 Python 子集出发的前端，以及后端各阶段的 Python
实现。其 C 路线经过类 C 子集；直接路线跳过该阶段而生成 `.mg`。结构化的 LAL 和
内存映像接口可以替代序列化的中间文件，结果仍然在 Malbolge20 机器上执行。
Python 函数、算术辅助例程和十进制 I/O 属于编译器与运行库功能，并没有扩展语言的
八条具名指令。可接受的 Python 语法及其与 CPython 的差异见
[Python 子集规范](../specs/python-subset-spec.zh.md)；中间语言见
[`.mg` 规范](../specs/mg-spec.zh.md)。

## 证据与限制

上述规范源码版本于 2026-10-27 直接读取。其解释器文件的 SHA-256 为
`0ea5d2cfd8e597256f91bae3ea505f2f8467e3704e5c362b24fc91b56b9782b0`，
与本项目独立参考验证所固定的文件内容相同。数值例子和操作码余数已对照源码表及
当前项目实现核查；本文不宣称运行性能或完整符合性。论文题名与作者名来自官方项目页，
期号、日期和报告号来自机构库记录；本文没有声称重新阅读全文。
获取独立固定版本的 C 参考实现，见
[参考工具设置](toolchain-guide.zh.md)。
