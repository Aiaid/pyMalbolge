# docs 索引

> [English](README.md) | **中文**

本目录叙述性文档有中英两版：`<name>.md`（英文）与 `<name>.zh.md`（中文），
内容保持同步。机器可读测量数据由两种语言共享一份 JSON，不复制为翻译版本；逆向工程类笔记以中文版为原稿。文档按类别分子目录存放,
双语成对移动;状态标记:✅ 现行 / 🧊 已搁置 / 📌 历史快照(保留原样,
带取代注记)。

## specs/ — 语言规格

| 文档 | 状态 | 内容 |
|---|---|---|
| [mg-spec.zh.md](specs/mg-spec.zh.md) | ✅ | `.mg` 伪指令语言规格(逆向自 `ternary`,含实验验证) |
| [hell-spec.zh.md](specs/hell-spec.zh.md) | ✅ | HeLL 语言规格(逆向自 LMAO v0.6.0) |
| [python-subset-spec.zh.md](specs/python-subset-spec.zh.md) | ✅ | **规范性规格**:接受的 Python 子集 v1——按 AST 节点的接受白名单、与 CPython 的分歧(D1–D19)、诊断契约、审计附录 |

## design/ — 设计与路线

| 文档 | 状态 | 内容 |
|---|---|---|
| [native-jit.zh.md](design/native-jit.zh.md) | ✅ 本地显式试验 | 真实带守卫 ARM64 NOP 代码生成、精确退出/COW/预算、冷暖证据及短夹具性能回退 |
| [native-vm.zh.md](design/native-vm.zh.md) | ✅ 本地显式原型 | Python 接口接原生 Malbolge20 执行/内存核心；正确性、快照、本地构建、同映像测量和带守卫 JIT 边界 |
| [highlevel-to-malbolge.zh.md](design/highlevel-to-malbolge.zh.md) | ✅ | 路线决策:高级语言→Malbolge 可行性、推荐管线、里程碑、Python 前端 v1 与直连后端 |
| [optimization-status.zh.md](design/optimization-status.zh.md) | ✅ 带日期快照 | 全部优化层、已验收/默认/opt-in/本地原型状态、证据索引及未解决边界 |
| [py2mg-backend.zh.md](design/py2mg-backend.zh.md) | ✅ | `py → .mg` 直连后端(`--backend=direct`)设计:栈帧策略、递归环检测、与 C 路径的体积对比 |
| [compiler-ir.zh.md](design/compiler-ir.zh.md) | ✅ | 可选 LAL/语义边界、可校验 pass 基础与迁移里程碑；变量 SSA、优化、布局和 LLVM/MLIR 仍待实现 |
| [semantic-ir.zh.md](design/semantic-ir.zh.md) | ✅ | 直接 Python AST 前端、类型化语义 IR、独立执行器、显式目标适配器、CLI 选择与诊断边界 |
| [semantic-optimization-passes.zh.md](design/semantic-optimization-passes.zh.md) | ✅ profile 已验收，十进制实验 | 具名语义算术/数据流/控制/发射 pass、目标算术开关、等级 0/1 与完整比较契约 |
| [structured-lowering.zh.md](design/structured-lowering.zh.md) | ✅ 显式试验 | 无额外依赖的 MG→LAL→内存映像→MB 传递、可选 xDSL 适配、CLI/缓存选择及行为优化验收 |
| [hell-assembler-design.zh.md](design/hell-assembler-design.zh.md) | 🧊 | Python 版 HeLL 汇编器设计(已搁置的备选路线;§6 讨论 GPL 问题) |
| [tui-web-architecture.zh.md](design/tui-web-architecture.zh.md) | ✅ | 调试器 UI 架构:三层切分,`malbolge/view/` ViewModel 仅输出 JSON,由 Textual 渲染层与(待定的)Pyodide web 版共用;所需的三个后端 API;分阶段与并行边界 |
| [tui-redesign/README.zh.md](design/tui-redesign/README.zh.md) | ✅ | 导入的 TUI 重设计画布(四块画板:现状复刻、信息密度最大化、教学向、80×24),附可离线打开的 `preview.html` |

## upstream/ — 上游参考与考古

| 文档 | 状态 | 内容 |
|---|---|---|
| [toolchain-guide.zh.md](upstream/toolchain-guide.zh.md) | ✅ | 外部参考工具链的构建与复现指南(平台坑、确定性、验证惯例);编译已不需要外部工具,保留给 conformance 对拍与考古 |
| [lmao-internals.zh.md](upstream/lmao-internals.zh.md) | ✅ | LMAO 汇编器内部算法分析(布局、自举生成) |

## notes/ — 工程笔记

| 文档 | 状态 | 内容 |
|---|---|---|
| [native-jit-validation.json](notes/native-jit-validation.json) | ✅ 本地显式验收 | JIT 语义/审查/ABI/打包、同映像五模式三轮计时、发射/覆盖率/预热成本及首次预热被拒记录 |
| [native-vm-validation.json](notes/native-vm-validation.json) | ✅ 本地显式验收 | 原生 VM 正确性、审查、ABI/打包检查和五轮同映像 Python/原生/C 执行测量 |
| [compiler-ir-validation.json](notes/compiler-ir-validation.json) | 📌 | 首次 LAL/pass 基础验收及源码指纹；后续前端/集成变更由 semantic-ir-validation.json 覆盖 |
| [semantic-ir-validation.json](notes/semantic-ir-validation.json) | 📌 | pass 启用前的语义架构验收；后续变更由 semantic-pass-validation.json 覆盖 |
| [semantic-pass-validation.json](notes/semantic-pass-validation.json) | ✅ | 已提交的 pass/默认策略验收；本地目标接口实验另行记录 |
| [target-interface-validation.json](notes/target-interface-validation.json) | 📌 | 尚未提交的本地原型：目标 AST 角色、默认策略、回归与实现指纹 |
| [structured-lowering-validation.json](notes/structured-lowering-validation.json) | ✅ 本地验收 | 原生低层接口回归、库/CLI/IR 接入和测量范围 |
| [perf-baseline.zh.md](notes/perf-baseline.zh.md) | 📌 | QoS 修复前性能剖析基线；运行时表示/热点描述已由紧凑周期内存与 python-qos-validation.json 取代 |
| [fib-input-performance.json](notes/fib-input-performance.json) | 📌 | QoS 修复前的 2026-10-08 共享测量数据：普通 Python Fibonacci、direct 编译、优化 C 参考解释器执行、CPython 对照及项目 Python CLI 的资源受限停止；双语解读见主 README |
| [python-qos-audit.json](notes/python-qos-audit.json) | 📌 | 历史十一组反例；由 python-qos-validation.json 结案，原证据保留 |
| [python-qos-validation.json](notes/python-qos-validation.json) | ✅ | 最终本地验收、原生/便携 VM 证据、新旧产物、有界运行/存储、缓存与汇编测量；已配置云端 CI，尚未运行 |

另有研究笔记(发现清单、设计方案 `mb-dialect-plan`、全方向 `roadmap`、
名古屋数组解剖、生态全景调研等)保存在一个私有的配套仓库中,不属于
本仓库;本目录其余文档偶尔会按条目编号引用它们。

运行时库文档见 [`runtime/mg/README.md`](../runtime/mg/README.md);
固定 Python 基准程序与 CSV/JSON 执行器见
[`benchmarks/README.zh.md`](../benchmarks/README.zh.md);
测试夹具出处见 `test/fixtures/hell/README.md` 与 `test/fixtures/nagoya/README.md`。
