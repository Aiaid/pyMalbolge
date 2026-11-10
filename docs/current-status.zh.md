# 当前实现与发行边界

> [English](current-status.md) | **中文**
>
> 文档核对日期：2026-11-10。实现状态指源码工作树，包含 `0321a26` 中的共享源码
> 分析提取。发行与基准结论保留各自带日期的来源；本文不是新的全量测试、
> 平台或性能验收报告。

## 已实现

- **编译器：**受限 Python 子集经 C、direct MG 或可选语义 IR 编译到
  **Malbolge20**。O3/auto 按预测最终映像大小比较适用的 Direct 与已验收 semantic
  候选，再只生成一次 bootstrap。O2/O3 默认使用结构化 LAL/内存映像传递。
- **架构：**语义 IR 已有表达式 SSA、可变源码槽位、经校验的具名 pass 和独立执行
  oracle。目标路径仍是语义 IR → 目标 AST → MG → LAL → 内存映像 → MB。
  共享 AST 分析已集成到源码中；1.1.0 发行回执不覆盖这次提取。
- **语言：**无符号 20-trit 整数、标量/控制/函数语法、递归，以及规格限定的十进制
  I/O、平坦 tuple 赋值、关键字调用和基本 print f-string，并非完整 Python。
  semantic 在部分死代码和局部绑定场景下比 Direct 更严格。见
  [子集边界](specs/python-subset-spec.zh.md#01-后端边界)与
  [语义兼容性](design/semantic-ir.zh.md)。
- **执行：**Original Malbolge 和 Malbolge20 都有 Python 解释器。
  Malbolge20 的 `run20` 和批处理 CLI 默认优先使用可加载的原生 VM，否则回退
  Python。Original、调试器、旧 `eval20` 和非批处理终端流式执行仍走 Python。
  导入与执行不会调用编译器构建扩展。
- **浏览器：**[静态 Pyodide 调试器](https://aiaid.github.io/pyMalbolge/)
  已实现，仅支持 **Original Malbolge**。
  [本地浏览器验收](notes/web-demo-validation.json)和
  [托管部署证据](notes/web-demo-deployment.json)分别记录。
  `malbolge/tui/` 已存在不等于完整 TUI 重设计已经完成。

## 已发行与实验的区别

**[1.2.0 已发布到正式 PyPI](https://pypi.org/project/malbolge/1.2.0/)。**
源码提交：`65c44bf7ee112f0df8c85b64b1c826787713492b`。
[正式运行 42782746293](https://github.com/Aiaid/pyMalbolge/actions/runs/42782746293)
通过 GitHub OIDC Trusted Publishing 上传 35 个原生 wheel、一个便携 wheel 和
一个 sdist。全部 37 个公开产物哈希、七个同提交质量 CI 作业及 13 组上传前
安装/输入检查通过。上传后 13 组远端安装/输入检查也全部通过；最终各组结果及精确产物身份见
[正式发布回执](notes/pypi-1.2.0-publication.json)。

发行编译器/VM 保留 rc2 基线，未发布未提交的实验 JIT 修改。
[rc2 回执](notes/release-1.2.0rc2-testpypi.json)保留为独立历史证据，不替代
正式产物检查。macOS ARM64 的 deployment target、标签与 Mach-O 最低系统为
15.0，精确 macOS 15.0 运行兼容性仍未测试。rc2 及正式版五个 ARM64 ABI 的实际宿主均为 15.8.2。正式托管 Mac JIT 不可用，
保留守卫并显式拒绝；Linux ARM64 NOP JIT 执行为另一项证据。本地
Mac/CM4 执行只证明对应设备，不构成普遍提速结论。

[PyPI 1.1.0](https://pypi.org/project/malbolge/1.1.0/) 于 2026-10-27 发布，包含
**30 个原生 wheel、一个便携 wheel 和一个 sdist**。原生 wheel 覆盖 CPython
3.9–3.13 的 Linux glibc/musl x86-64/ARM64、Windows x86-64 和 macOS Intel。
Python 3.8 兼容性检查与这份 wheel 矩阵分开。见
[发行说明](notes/release-1.1.0.zh.md)及
[产物哈希和安装验收](notes/pypi-1.1.0-publication.json)。

Apple Silicon wheel 已正式发布；精确最低系统版本运行测试仍待完成。本地 macOS ARM64 能运行
不证明所有标签声明的最低系统版本均兼容。带守卫的 ARM64 NOP JIT 是
**显式启用的实验功能**，不是默认引擎或通用 LLVM 后端；合成 NOP 用例收益与
真实短夹具回退同时存在。见[打包](design/native-packaging.zh.md)和
[JIT 范围](design/native-jit.zh.md)。

## 仍属于设计或后续工作

直接 semantic→LAL lowering、完整源码变量 SSA/活性分析、新协议/布局接管、
LLVM/MLIR 适配、`.ll` 前端、通用运行时数组/字符串/对象、有符号整数和
Malbolge Unshackled 都不是当前产品能力。可选 xDSL dialect 和小范围原生 JIT
不等于这些功能已经实现。应区分设计、本地实验、已验收默认行为与已发布分发包。

## 如何解读对照结果

[上游指南](upstream/toolchain-guide.zh.md)区分冻结的旧版 Nagoya 参考与 GitLab.com
整合工具链。公开 issue 针对特定复现与版本，不能据此断言最新上游 main 未修复。
两个解释器一致运行一个错误映像不等于源程序正确：还要核对预期输出、输入消耗、
错误与终止。

带日期的 benchmark 保留原始源码/映像/引擎身份、超时和平台边界，不改标为当前
工作树的测量。IR 大小、wheel 可用性或旧 Python-only 计时都不能推出当前速度。
