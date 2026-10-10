# 结构化低层后端传递

> [English](structured-lowering.md) | **中文**
>
> 当前分支更新，2026-10-10：按[编译策略](compiler-optimization.zh.md)，
> structured 已成为 O2/O3 默认；text 可显式选择，也是 O0/O1 默认。
> 该接口最初以保持生成风格、协议、布局与填充策略的实验方式提供。
> 原验收继续作为历史证据，本次组合集成见
> [新增验收记录](../notes/compiler-optimization-validation.json)。

## 数据流

```
Python 前端 → MG → 无额外依赖的 LAL 记录 → MemoryImage → MB
                         ↕ 可选、可校验的 xDSL LAL
```

`translate_mg_to_lal` 复用现有 MG 解析与 lowering，以类型化生成器直接
输出记录，避免生成完整 MC 字符串后再次解析。固定 DJMP/IND_OPR 模板在
模块加载时一次性转成不可变记录。`layout_lal_to_image` 直接消费记录，
共享既有打包、地址解析、BASE 和内存放置逻辑。启动生成器直接消费有序
映像段，避免 `.data` 序列化。

MC 和 `.data` 继续作为导出格式与参考适配器。旧读取器保持既有接受范围
和错误行为。结构化 MC 的规范导出保持语义与声明顺序，空白与注释不保留。

## 契约

- `lal_model.py` 提供不可变目标、flag、unit、routine、数据字与显式指令。
  UNIT 偏移顺序（含重复/递减偏移）和 continuation 预留间隔具有语义意义。
  校验覆盖类型、作用域、声明顺序、字宽和旧命名歧义。
- `memory_image.py` 提供 `MemoryImage(entry, segments)` 与
  `MemorySegment(kind, index, offset, words)`。映像段顺序与未设置值 `-1`
  具有语义意义。entry 是原有的例程分派描述符地址，不保证 VM 把该地址
  当作指令执行。
- 基础 C/direct 路径继续兼容 Python 3.8，不导入 xDSL。可选 IR 路径将
  记录适配为可校验 xDSL operation，再把变换后的 module 转回记录。
  变换后的 module 是权威输入，汇编不会复用 pass 之前的对象。
- IR 报告与缓存导出可以序列化诊断 IR/MC；这些导出不承担原生汇编传递。
  本轮没有引入直接源语义→LAL lowering 或完整变量 SSA。

原生汇编对旧布局尚不支持的 ALIGN、跨 routine ADDRESS、BRANCH 减法和
跨 routine JMP 减法显式报错，不静默退回旧文本解析器。

## 选择与导出

```sh
uv run python -m malbolge compile examples/hello.py \
  --backend direct --target-pipeline structured -o hello.mb
uv run python -m malbolge compile examples/hello.py \
  --backend ir --target-pipeline structured --emit-ir hello.mlir \
  --emit-mc hello.mc -o hello.mb
```

整程序编译现在默认 O3/structured，仍可显式使用
`compile_python_to_mb(..., target_pipeline="structured")`。
编译器另导出原生 MG→LAL、LAL→image 和 LAL/image→MB 函数，包含流式字节
输出。旧 MC API 与 `target_pipeline="text"` 继续用于对照。

缓存标识包含目标管线选择。原生阶段指标标注结构化表示，不虚构必经的
MC 产物；完整映像缓存命中保持既有的原子复制行为。

## 验收与优化

本次接口变更以 MC/data 含义、最终 MB 字节和 VM 结果一致，验证传递方式
改变而生成行为保持。后续生成优化允许字节、地址和执行步数变化；验收
依据是可观察语义（输出、输入消耗、错误与终止）、必要机器不变量，以及
分别测量的编译时间、最终体积和执行成本。字节一致不是优化目标。

测试覆盖四种风格、输出有定义的夹具、间接访问模块、禁用完整文本接口
后的原生执行、流式输出、可选 IR 权威性、CLI 导出/缓存隔离及无 xDSL
基础导入。测量与各层独立热点分析保留在私有配套研究记录；验收指纹见
[`structured-lowering-validation.json`](../notes/structured-lowering-validation.json)。
