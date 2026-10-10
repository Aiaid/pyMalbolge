# 编译器优化策略

> [English](compiler-optimization.md) | **中文**
>
> 状态，2026-10-10：O3 策略与目标接口实现已集成并通过本地验收。
> [集成验收](../notes/compiler-optimization-validation.json)记录完整回归、最终定向
> 检查及全部 12 个完整所选映像指纹。较早的性能记录保留各自冻结 cohort 范围。

## 默认编译

CLI 与 `compile_python_to_mb()` 默认使用 `backend="auto"`、优化等级 3、
`target_pipeline="structured"` 和既有 `cluster/main` 风格。适用的已验收
变换自动启用；显式后端、前端、目标管线与 pass 选择仍控制各自范围。

```sh
uv run python -m malbolge compile program.py -o program.mb --stats
uv run python -m malbolge compile program.py -O0 --no-cache -o reference.mb
uv run python -m malbolge compile program.py --backend=direct -o direct.mb
uv run python -m malbolge compile program.py --target-pipeline=text -o text.mb
```

O3 auto 总是准备 direct 候选；当 Python 3.10+ 和锁定版本的可选 `ir`
extra 可用时，同时准备采用已验收有序 pass profile 与目标接口开关的
semantic 候选。两个候选都只推进到已校验的 LAL 记录和完成布局的
`MemoryImage`，选择预测最终 MB 更小者，相等时选 direct。只有胜出候选
生成启动代码；显式选择最终 `text` 传递时也遵循这一规则。

对固定源码、工具链、选项和可选依赖环境，尺寸选择是确定性的。安装 IR
extra 会增加候选，因此可能改变选中的产物。本策略不保证每个负载运行最快
或总编译成本最低；即使 direct 胜出，候选准备仍有成本，较小产物也不是
通用的运行时间模型。

## 等级与显式选择

下表假定没有显式指定后端、前端、pass 列表或目标传递方式。

| 等级 | 前端选择 | direct 算术捷径 | 目标传递 | CLI 自动缓存 |
|---|---|---|---|---|
| O0 | direct | 关闭 | text | 关闭 |
| O1 | direct | 开启 | text | 关闭 |
| O2 | direct | 开启 | structured | 关闭 |
| O3，默认 | direct 与适用的已验收 semantic 比较 | 开启 | structured | 开启 |

CLI 的 `-O0` 至 `-O3` 与 `--opt-level=0` 至 `--opt-level=3` 等价；
库接口使用整数 `opt_level` 关键字参数。

- `--backend=c`、`direct` 或 `ir` 锁定后端并关闭竞争。显式 IR 在所有
  等级默认使用 `semantic`；`--ir-frontend=compat` 恢复原 direct→LAL 兼容桥。
- semantic O0 只执行校验，同时关闭省略生成局部初始化、结构化循环条件
  prelude 和原生条件 predicate。semantic O1–O3 使用同一已验收 pass
  profile，开启这三个表示开关；更高等级不会凭空增加另一套 pass。
- C 是参考前端，O0 仍保留固有常量折叠和算术恒等式。元数据用
  `c_reference_intrinsics` 明确标记；C0 不是完全无算术优化的基线。
- `--target-pipeline=text` 或 `structured` 覆盖等级默认传递方式。
  `--op-style` 和 `--jmp-style` 仍显式选择，O3 不遍历四种风格。
- `--semantic-passes` 指定精确的有序语义序列；`--passes` 控制 LAL pass。
  CLI 的 `--semantic-passes` 与显式优化等级互斥。库中显式
  `semantic_passes` 序列覆盖该等级的语义 profile，但 O0 仍关闭目标表示捷径。
- CLI 省略后端时按检查输出推导：`--emit-c` 选择 C，IR 检查选择 IR；
  显式不兼容的后端/输出组合会报错。不指定输出选项时，默认 auto 打印
  胜出候选的 MG；原来的 C 检查行为可用 `--emit-c -`。

O0 保留语法校验、错误检查、必需规范化和所选后端的调用约定。单阶段 API
继续保留各自契约，例如 `compile_python_to_ir()` 保留原兼容桥默认值，
不会继承整个程序的候选选择器。

## 可选 IR 与错误边界

基础编译器仍支持 Python 3.8+，没有必需依赖；导入时不加载 xDSL。O3 auto
会在 Python/xDSL 环境缺失或不兼容时跳过 semantic；对 direct 已接受的
源码，也可依据 semantic 前端的不适用诊断跳过该候选。选择与原因会记录，
不会自动安装依赖。

显式 IR 请求要求受支持环境，遇到错误会报告，不改变后端。校验、优化、
目标 lowering 和布局失败不会作为候选不适用处理。语义 module 始终是权威
输入，不回放原始源码，也不进行任意回退。

```sh
uv sync --extra dev --extra ir
uv run --no-sync python -m malbolge compile program.py --backend=ir \
  --ir-frontend=semantic -o semantic.mb --stats
```

## 生成启动代码之前的精确尺寸

`mc2mb.predict_image_mb_size(image)` 检查标准段顺序、direct 偏移与启动
代码预留空间，以及合法的 direct 源指令。成功汇编要求启动代码终点不超过
最后 direct 段的偏移，因此 direct 源码单元确定最终输出最高位置。加上与
实际发射共用的尾部对齐和两个字节，即得到精确 MB 字节数，无需生成启动指令。

预测以成功汇编为前提，不能证明程序正确或预留启动空间足够；不受支持的
原始镜像会明确报错。汇编器仍执行自身的重叠及其他检查。LAL 操作数、IR
大小和地址空间跨度都不能替代这一最终文件指标。

## 缓存与来源记录

O3 CLI 自动使用源码文件旁的 `.cache/malbolge`。自动持久化只接纳每项不超过
**64 MiB** 的产物；这是单产物门槛，不是缓存目录总配额，更大的输出仍可编译。
`--no-cache` 关闭持久化；`--cache-dir PATH` 显式选择不受自动门槛限制的
缓存，在较低等级也可使用。库编译不创建持久缓存。

输出使用原子替换，检查输入/输出/缓存产物路径别名；缓存命中要求大小与
SHA256 一致。无效 manifest 或损坏产物视为未命中。自动缓存不可用不应
阻止写入有效的用户输出；显式缓存 I/O 错误仍会报告。auto 在完整 MB 缓存
命中前仍准备候选并确定选择，不声称跳过前端工作或重放缓存中的 pass 报告。

`--stats` 与缓存来源记录保留请求/解析后的策略、胜出候选、精确候选尺寸与
选择原因、可选 IR 状态、有序语义 pass 和目标开关。缓存键还包含源码/工具链
指纹、Python、适用时的 xDSL、生成风格与目标传递方式。冷编译性能测量必须
传 `--no-cache`，热缓存复用作为独立结果报告。

## 已接受范围与证据

默认 profile 排除曾出现成本回退的实验十进制输出 pass，也不启用已拒绝的
批量 NOP 发射方案。运行引擎选择与 JIT 独立于编译器 O3：JIT 继续显式
启用，不由本策略开启。原生打包和 VM 默认行为有各自验收记录。

[语义 pass](../notes/semantic-pass-validation.json)、
[结构化接口](../notes/structured-lowering-validation.json)、
[目标接口](../notes/target-interface-validation.json)与
[同 VM 比较](../notes/common-vm-validation.json)保留原来的测量范围。
目标接口源码已集成，旧原型测量本身不能证明本次策略变更已验收；顶部
集成记录负责最终组合检查。编译时间、精确产物大小和同 VM 执行继续分别验收。
