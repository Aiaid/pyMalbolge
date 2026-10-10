# Python 前端与语义 IR

> [English](semantic-ir.md) | **中文**
>
> 状态，2026-10-09：直接 AST 前端、结构化语义 dialect、独立执行器及显式
> 目标适配器与已验收优化 pass 已实现。完整源变量 SSA 和直接语义→LAL
> lowering 仍待完成；性能证据与本架构契约分开记录。

> 当前分支更新，2026-10-10：此前已记录的目标接口实现已与
> [O3 默认策略](compiler-optimization.zh.md)一同集成并通过本地验收。原原型验收保留为历史
> 证据；最终组合验收[单独记录](../notes/compiler-optimization-validation.json)。
> 集成不代表性能已与 direct 持平。

## 1. 两条明确的前端路径

语义路径在生成 MG 或 MC 之前构造 IR：

```text
Python AST → 共享规范化与源码检查 → pysem 语义 IR
  → 可校验语义 passes → 目标 AST 适配器 → MG → 原生 LAL 记录
  → 可选、可校验 xDSL LAL passes → MemoryImage → 现有启动代码 → MB
```

此前适配器从语义 IR 重建并序列化 Python AST，再交给 direct 生成 MG。
当前分支的目标接口直接交接采用 Python 结构的目标 AST，避免文本往返。
两种表示均不回放原始源码，也不在不透明 IR 操作里保存 AST。修改语义 IR 会
改变后续代码与执行结果。未来可替换目标 lowering，而无需替换该前端。

显式 `--backend=ir` 现在默认 `--ir-frontend=semantic`，包括 O0；
`--ir-frontend=compat` 保留原 direct→MG→MC→LAL 桥。请求
`--emit-semantic-ir` 会选择 semantic，除非与显式选择冲突。显式 IR
不回退；O3 auto 可报告原因后跳过不可用或不适用的 semantic 候选，但
校验、lowering、布局错误仍报告。基础 C/direct 仍无必需依赖。

```sh
uv sync --extra dev --extra ir
uv run --no-sync python -m malbolge compile demo.py --backend=ir \
  --opt-level 0 --emit-semantic-ir /private/tmp/demo.semantic.mlir
uv run --no-sync python -m malbolge compile demo.py --backend=ir \
  --ir-frontend=semantic --emit-ir /private/tmp/demo.lal.mlir \
  -o /private/tmp/demo.mb --stats
```

两种用法均要求锁定版本的可选 xDSL 环境及 Python 3.10+。仅导出前端 IR
不会调用目标适配器，也不会生成 MG/MC/MB。

保存的 [IR 示例](../notes/semantic-ir-example.mlir)来自：

```python
def next_byte(value):
    return value + 1
byte = getchar()
putchar(next_byte(byte))
```

独立执行器与实际编译的 MB 均只消耗一次输入 `A` 并输出 `B`。文件包含
结构化函数、槽位、SSA 算术、调用和 I/O，并保留原始源码位置。

## 2. 表示与副作用契约

`pysem.word` 固定为 20 trits，值域为 `[0, 3**20)`；加、减、乘在该域内
回绕。整除/取模是带检查的操作，保留零除副作用。原始前端不折叠或强度
削弱合法算术；在显式选择/默认优化 pass 之前，`n * 17` 仍然是乘法。

表达式结果使用 SSA；源变量仍是带 load/store 的显式 local/global 槽位。
因此本阶段没有完整变量 SSA、phi 构造、全程序活性分析或优化器。
程序全局槽位从零开始；局部槽位需要实际执行绑定。参数是字值 block
argument，存入相应源码槽位。

| 结构 | 表达的语义 |
|---|---|
| 程序/函数 | 入口、声明、参数、局部变量、显式 global，以及 word/void/optional 返回契约 |
| 常量、读写、二元/一元操作 | 值与可变位置分离，没有隐式重复求值 |
| 布尔与比较 regions | 惰性操作数、返回操作数的 and/or、链式比较中间值只求值一次 |
| 条件表达式与语句 | 仅执行选中的分支，值不能越过 region 泄漏 |
| while/range 循环 | 每轮求值的条件 region、已捕获 range 边界、独立迭代状态、有符号常量步长及倒序 stop=-1 哨兵 |
| 调用/return/break/continue | 有序实参值、直接符号、显式控制转移与循环作用域 |
| 字节与十进制 I/O | getchar/putchar、字面量/字值输出、带字面量提示的检查式整数输入 |
| 未绑定名称陷阱 | 为已接受的静态不可达未知读取保留显式副作用，不伪造零值变量 |

内存、调用、I/O 和检查式错误不标为纯操作。语句和表达式生产者按顺序执行；
后续 pass 必须保持这些副作用，结构校验本身不能证明语义等价。
校验器检查字类型/范围、词法 SSA 支配、作用域、调用元数、region yield、
控制位置及可达返回契约。源码位置在 IR 打印和重新读取后仍保留。

前端使用 CPython 语法/符号表检查、共享 normalizer 及纯 AST 诊断分析；
生成 IR 时不实例化或运行旧编译器。平坦元组、基础 print f-string 和
关键字绑定转换为显式、有序的语义操作。
纯 AST 分析目前通过 direct 前端的方法别名复用；迁到共享源码分析模块
仍是独立架构整理项，与目标 lowering 和优化分开。

## 3. 检查与独立执行

`malbolge.compiler.ir` 的延迟加载 API 包括：

| API | 用途 |
|---|---|
| compile_python_to_semantic_ir(source) | 目标代码生成前的已校验源码 IR |
| compile_python_semantic_result(source, passes=None, snapshots=False) | 语义 pass 结果、克隆、报告和可选快照 |
| print_semantic(module) / parse_semantic(text) | 包含源码位置、确定性且可检查的 IR |
| run_semantic(module, input_data=b'', ...) | 独立分发语义操作，带操作/调用/深度/输出预算 |
| lower_semantic_to_python_ast(module) / lower_semantic_to_mg(module) | 从 IR 重建的兼容表示 / 目标 MG |
| lower_semantic_to_target_ast(module)（当前分支集成） | 显式保留生成局部角色和循环条件计算区的后端契约 |
| compile_semantic_to_mc(module, ...) | 适配器及可校验 LAL 目标管线 |

当前集成分支的后端契约位于 `compiler/target_ast.py`，不依赖 xDSL。
`TargetAST` 按函数显式
携带生成局部名字；`TargetWhile` 携带每次判断前依序执行的
`condition_prelude`。不按名字前缀分类。生成局部仍是有普通存储、受递归
栈帧保护的变量，不是后端临时分配池中的变量。语法和确定赋值检查仍执行。

`compile_target_ast_to_mg` 接收该结构化契约。`lower_semantic_to_mg` 同样
提供独立的 `skip_generated_initialization` 和 `structured_while` 对照
开关：前者只省生成局部的入口清零复制，后者避免在循环体伪造 break。
源槽位、参数复制、源码 break/continue 与错误传播保持原契约；Python
源码编译仍使用独立入口。

`native_conditions` 是第三个独立的适配器开关。条件区末尾单一比较若只供
该区 yield 使用，可以保留为原生 predicate；前缀及左右操作数仍依序计算，
使用已捕获的 SSA 值。链式比较、额外消费者及其他条件 producer 保留字值
表示。作为数字使用的比较仍输出 0/1；资格从当前已校验图重新检查。

整程序 semantic 编译在 O1–O3 开启三个接口开关，在 O0 关闭。低层适配器
仍提供各自独立开关；全部传 false 可对照旧目标表示，但不改变独立选择的
语义 pass 列表。十进制算法选择独立：实验十进制 pass 仍不属于默认 profile。

结构化目标 AST 不能直接当普通 Python AST 执行：CPython 不会执行其额外
prelude 字段。显示或普通域 Python oracle 应用 `to_legacy_ast` 显式展开，
或使用原有 `lower_semantic_to_python_ast` 视图。字环、效果及错误的完整
参考仍为独立语义执行器。

执行器不使用 Python exec/AST 重建、旧编译器或目标 VM。它报告输出字节、
输入消耗、全局状态、返回值及停止/预算/错误状态。文本输入按 UTF-8 编码，
与有界目标 VM 一致；字面量输出遵循子集的字节码点契约。运行时整数输入/
除法失败只输出一次 `error\n`，然后停止入口。操作计数用于该执行器的
预算，不是 Malbolge 步数或性能指标。

语义与 LAL pass 注册表分离；语义默认使用
[已验收优化 profile](semantic-optimization-passes.zh.md)，等级 0 只做
verify-semantic，LAL 默认仍为 verify-lal。
共享 runner 校验输入及每个 pass 输出，默认克隆。语义报告只有 IR 字节/
计数/摘要，不在 lowering 前虚构 MC/MB 成本。--semantic-passes 选择语义
pass，--passes 继续选择 LAL pass。缓存标识包含前端与两层有序选择；
命中报告说明来源，不伪称重新执行了 pass。

## 4. 兼容边界与验收

语义前端实现已文档化的标量/控制/I/O 形式；以下边界适用于显式使用与
O3 候选的适用性判断：

- 不支持的语法即使位于静态不可达分支也会拒绝。旧前端在发射常量分支时
  有时跳过这些语法。
- 即使模块全局同名，也拒绝局部绑定之前的读取；旧分析可能放行。
  函数隐式全局读取仍要求模块绑定名称；函数 global 写入只声明存储，
  不扩大其他函数的隐式读取范围。
- 常量零除源码错误保留原始位置；动态零除/输入错误保留为运行时操作。
  显式陷阱保留已接受不可达 region 中的受支持未知名称读取。
  IR 修改后若到达陷阱，会给出语义执行诊断，不伪造值，也不新增可达源码
  未知读取的接受范围。
- 适配器会增加新捕获、名称映射和入口包装，目标产物可能不同或更大。
  不以字节一致或提速作为本阶段承诺。CPython 交叉检查仅用于值域有效的
  AST 执行；字环和错误行为由 IR 执行器规定。
- 目标协议/布局仍使用既有 MG/MC 机制及已记录的 LAL 解析限制。直接
  语义→LAL 和 LLVM/MLIR 适配尚未实现。

测试覆盖不调用旧代码生成的源码 IR、固定负载输出、源码诊断定位、IR
修改权威性、有序/惰性副作用、序列化和 pass 失败，以及代表性实际 MB
执行。机器可读范围见
[`semantic-ir-validation.json`](../notes/semantic-ir-validation.json)。

本阶段为后续分析和目标专用 lowering 提供位置。新优化候选需要分别完成
语义与编译时间/体积/运行时间验收，才能加入当前已验收默认 profile。
