# 结构化编译器 IR 与 pass 边界

> [English](compiler-ir.md) | **中文**
>
> 状态，2026-10-09：LAL、可选语义前端与已验收 pass 已实现；完整变量
> SSA、新布局及 LLVM/MLIR 适配器仍属计划。本文件独立于私有研究笔记描述新增的公开架构，
> 不声称带来性能提升。

## 1. 首个里程碑与兼容性

首个里程碑为现有低级汇编（LAL，`.mc`）边界增加结构化、可验证的表示，
引入具名 pass 和检查产物，同时沿用现有汇编器。Python 路径为：

```text
Python 子集 → 现有 direct 前端 → .mg → 现有 MG 翻译器 → .mc
  → 结构化 LAL IR → 显式项目 pass 管线 → .mc → 现有 mc2mb → .mb
```

该默认 `ir` 前端仍是 `compat` 兼容桥。可选 `semantic` 前端已将 Python
AST 直接转为语义 IR，提供表达式 SSA 与显式可变槽位，目标 lowering 通过
权威兼容适配器完成，见[semantic-ir.zh.md](semantic-ir.zh.md)。完整源变量
SSA/活跃性分析仍待实现。现有默认 `c` 后端和显式 `direct`
后端保留其路径。接受的 Python 子集及语义差异仍以
[子集规格](../specs/python-subset-spec.zh.md)为准。

基础包继续支持 Python 3.8+，没有必需依赖。IR 是可选能力：`ir` extra
固定 `xdsl==0.69.0`，需要 Python 3.10+。导入解释器、普通编译器和普通 CLI
不能导入 xDSL；选择 IR 时检查运行时与依赖，并给出明确安装错误。
未来升级依赖必须重新验证。

```sh
uv sync --extra ir --extra dev
uv run python -m malbolge compile examples/hello.py --backend=ir \
  --emit-ir /private/tmp/hello.ir --emit-mc /private/tmp/hello.mc \
  --passes verify-lal -o /private/tmp/hello.mb
```

此示例使用 Python 3.10+。`--passes` 接受逗号分隔的项目注册 pass 名序列。
初始管线验证 LAL，不请求新增算术或布局优化。

## 2. LAL IR 表示什么

LAL operation 表示声明与可执行结构，不把整个程序装进一条不透明字符串。
声明顺序、标签、flag 状态/周期、变量/值引用、编号单元、unit 与 routine/
indirect 主体应以结构化字段和 region 保存。边界必须覆盖现有所有
`op_style`/`jmp_style` 组合产生的 MC，包括间接操作使用的周期 flag。

当前 `lal` dialect 提供 `entry`、`flag`、`jflag`、`unit`、`unit_label`、
`unit_cell`、`routine`、`label`、`instruction`、`data`、`align` operation
及结构化 `target` 属性。unit/routine 主体是 region；target 分别保存标签、
可选 routine 和减量。显式 unit offset 保持源顺序；重复/递减 offset 参与
旧汇编器的页面状态计数，不能排序消除。

解析器把文本语法转换为这些 operation；verifier 检查局部约束及模块级引用；
emitter 输出汇编器可消费的 MC。注释和空白不必逐字节往返一致，但声明与
指令顺序、引用含义、数值和机器行为必须保留。需要一致性时，测试对比
规范化 MC、汇编器内存数据及完整产物。

IR 解析器比旧正则解析器严格：拒绝畸形、截断或不支持的声明、重复符号、
非法 flag 状态及未解析引用，而非静默忽略。因此它不是旧解析器曾容忍的
任意输入的无限制替代。`ALIGN` 及部分分支/地址形式被显式表示，但仍保留
现有汇编器 resolver 的已知失败；可表示不代表已支持端到端执行。专项测试
保留这一限制，不静默改写其内存布局。

地址 word 和自定义 unit 调用的标签若以标准指令/unit 名称开头，则拒绝，
包括已限定 routine 的地址 target。旧汇编器按这些前缀分派，因此
`JMP_BACK` 等名称发射后可能被解释成另一条指令；应换用无歧义标签。
这一限制也防止裸标签与指令名或已声明 unit 符号冲突。

LAL IR 是机器/协议层。flag 或编号单元不等于推断出的 Python 变量；自修改
指令序列不能当作可自由重排的算术。结构验证检查表示本身，不证明源语义
等价、终止性或新布局不变量。

## 3. Pass 归属与可观察执行

每个发布 pass 都有稳定的项目名称与显式注册，通过 xDSL `ModulePass` 接口
执行，验证输入和结果，保留有序快照/digest 记录。未知名称在执行前拒绝。
仅验证 pass 是有用的基础设施，它公开了未来变换必须满足的同一边界。

| Pass 类别 | 适用层 | 契约 |
|---|---|---|
| 结构验证 | 当前 LAL IR；以后各 dialect | 结构、属性、引用与合法机器值 |
| 归一化/规范化 | 能证明规则适用语义的 dialect | 确定性形式；不改变隐含效果或错误 |
| 源语义优化 | 未来高级 IR | word 算术、有序效果、错误流与数据流事实 |
| 协议优化 | LAL IR | 保持 flag 转移、指令自修改及调度行为 |
| 布局/自举变换 | LAL 后的布局层 | 构造式放置/初始化不变量与产物验证 |
| 宿主实现优化 | 解析器、emitter、汇编器或 VM | 区分宿主速度与目标程序行为/成本 |

发布管线不悄然引入上游优化套件。复用上游 pass 需要显式项目适配器、
适用性审查与实际 dialect 语义验证。首个里程碑仅包含验证基础设施。

快照标识有序 pass 调用及前后状态。digest 是可复现性信号，不是等价证明。
保留证据时同时记录依赖版本、pass 顺序/选项和源代码/工具链指纹。
汇编器消费项目 MC emitter 的输出；xDSL 通用 printer 是检查格式，不是 MB
产物格式。

当前 API 从 `malbolge.compiler.ir` 惰性导入：

| API | 结果 |
|---|---|
| `parse_mc(text)` / `emit_mc(module)` | 已验证结构化 LAL / 规范汇编 MC |
| `parse_lal(text)` / `print_lal(module)` | 可往返的 xDSL 检查文本 |
| `verify_lal(module)` | 结构、有序声明、word 边界与作用域引用 |
| `run_pipeline(module, passes=None, snapshots=False)` | `PipelineResult`；默认克隆输入模块 |
| `mc_to_ir_result(text, passes=None, snapshots=False)` | MC 解析与已验证 pass 报告 |
| `compile_python_ir_result(source, ..., snapshots=False)` | 兼容前端与 `PipelineResult` |
| `compile_python_to_ir(source, ...)` / `compile_python_via_ir_to_mc(source, ...)` | 已验证模块 / 规范 MC |

`passes=None` 选择 `verify-lal`。库 API 的空序列显式选择零个 pass，但仍做
输入/输出验证。CLI 拒绝 `--passes` 的空名称；重复合法名称按指定顺序执行。
库自定义 registry 可引入项目 pass，不是 CLI 插件加载器。

`PipelineResult.to_dict()` 记录 `xdsl_version`、有序 pass 名和前后报告。
每个摘要含 SHA-256 `ir_digest`/`mc_digest`、总量/按名 operation 计数及
`mc_bytes`。`snapshots=True` 时还包含输入及每个 pass 后的文本。
CLI `--stats` 始终在 `ir` 下标识 IR 版本和选择的 pass 序列。冷管线记录完整
报告及 `cache_hit: false`；命中缓存时记录 `cache_hit: true`、
`cached_stage: "ir"` 或 `"mb"` 及空 `reports`，不伪造重放结果。
命中 IR 缓存时还记录当前摘要 hash/计数。`--emit-ir` 保存最终 IR，不是所有
中间快照。
缓存身份包含 IR 依赖/版本和有序 pass 配置；缓存完整性检查不能替代
pass 验证。

## 4. 验证与确定性门槛

在可能以不同方式失败的边界使用独立检查：

1. 对夹具和四种翻译风格产生的 MC 做解析/验证/发射/再解析；覆盖非法结构
   及未解析引用。
2. 对验收夹具，要求仅验证的 IR 桥接保持现有汇编器解析内存数据与 MB 产物。
3. 在不同 `PYTHONHASHSEED` 下重复检查规范 MC、IR 快照和 digest；把 operation/
   digest 预期绑定到 xDSL 版本，防止依赖升级静默重设基线。
4. 用有界 VM 运行代表性编译程序，比较输出字节、输入消费、终止/错误，
   必要时比较执行步数。
5. 检查没有 xDSL 的基础包及最低 Python 版本；可选 IR 语法和导入不得泄漏
   到普通执行路径。

这些检查验证相应夹具和环境。仅验证 pass 下的字节一致，不能证明未来变换
pass 正确。语义优化可以产生不同 MC/MB，此时行为、效果/错误和必要机器
不变量成为门槛。性能验收同时测冷编译 wall/CPU 时间、最终 MB 字节数和
产物运行 wall/CPU/步数；MC 体积或 IR operation 数量单独不足。区分自举
工作与程序执行，并将整个子进程超时独立于已测 VM 时间分类。

## 5. 迁移里程碑

| 里程碑 | 状态 | 完成条件 |
|---|---|---|
| 可选 LAL IR 基础层与 Python 兼容桥接 | 已实现 | 结构化 operation、解析/emitter、verifier、具名 pass runner、确定性检查与 CLI 集成 |
| 高级语义 dialect | 已实现 | 字环类型、有序 I/O/调用、惰性/控制 regions、返回契约及独立执行器；源变量仍用可变槽位 |
| Python 前端发射语义 IR | 已实现，显式选择 | 直接 AST 发射、源码诊断、明确兼容边界及权威目标适配器，见 semantic-ir.zh.md |
| 数据流与优化 pass | 有界 profile 已验收 | 具名算术/控制/数据流/发射 pass；完整变量 SSA、活性仍待实现，见 semantic-optimization-passes.zh.md |
| 布局/自举重构 | 计划 | 构造式不变量、反例回归与逐产物验证 |
| MLIR/LLVM 互操作 | 计划 | 显式类型/效果/lowering 适配器及经测量的引入理由 |

语义 word 类型表示 Malbolge20 无符号 word 域（`0..3**20-1`，算术模
`3**20`），而不是普通 LLVM 整数
溢出语义。启用常量折叠或死代码删除前，高级模型必须保留源表达式求值
顺序、输入/输出、调用/全局修改、错误守卫、返回传播及终止行为。
采用 xDSL 不会自动产生 MLIR/LLVM 后端；这些适配器是独立工程工作。

候选优化不会因为出现在表中就成为已实现功能。先用小程序验证每个边界，
再扩展覆盖面并逐项引入经测量的变换。

## 6. 代码位置

现有桥接组件：[`py2mg.py`](../../malbolge/compiler/py2mg.py)、
[`mg2mc.py`](../../malbolge/compiler/mg2mc.py)、
[`mc2mb.py`](../../malbolge/compiler/mc2mb.py) 与
[`cli.py`](../../malbolge/compiler/cli.py)。IR 实现见
[`ir/lal.py`](../../malbolge/compiler/ir/lal.py)、
[`ir/passes.py`](../../malbolge/compiler/ir/passes.py)、
[`ir/bridge.py`](../../malbolge/compiler/ir/bridge.py) 及
[`惰性 API`](../../malbolge/compiler/ir/__init__.py)。专项 dialect/管线/CLI 契约见
[`test_lal_ir.py`](../../test/test_lal_ir.py)、
[`test_ir_pipeline.py`](../../test/test_ir_pipeline.py) 和
[`test_ir_cli.py`](../../test/test_ir_cli.py)。基准用法和固定工作负载见
[`benchmarks/README.zh.md`](../../benchmarks/README.zh.md)。
