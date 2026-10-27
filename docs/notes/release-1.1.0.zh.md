# 1.1.0 发布

> [English](release-1.1.0.md) | **中文**
>
> 状态：2026-10-27 已向正式 PyPI 发布可移植 wheel 和源码归档。
> 对应默认主分支 `master` 的源码提交为 `0176888`。
> [发布与无缓存安装回执](pypi-1.1.0-publication.json)。

本版本汇总 1.0.0 之后的开发，并更新分发元数据。版本同时声明于
`pyproject.toml` 和 `malbolge.__version__`；PyPI 描述采用简洁的
[安装包介绍](pypi-description.zh.md)，不再直接展示带历史基准的长篇源码 README。

## 相对已发布 1.0.0 wheel 的变化

- 编译器 O0–O3 策略、适用候选自动选择、结构化 LAL/内存映像传递及有容量限制的 CLI 缓存。
- `ir` 扩展提供可选、经验证的语义 IR 工具（Python 3.10+）。
- 扩展 Python 子集，包括无符号十进制输入输出及规格中的元组、关键字调用、f-string 情形。
- 紧凑稀疏内存、有预算的字节批处理执行、可选原生 Malbolge20 VM、显式 ARM64 实验 JIT 与 Python 回退。
- 调试器 ViewModel 支持，以及单独托管、只支持原版 Malbolge 的浏览器调试器。
- Python 版本可移植性修复与 CI 固定 C 参考源码准备。
- 双语源码 README 更正上游当前维护、归属、seed 控制与历史对比说法。

规范性的 [Python 子集规格](../specs/python-subset-spec.zh.md)定义支持输入与语义差异。
默认编译策略和引擎选择与 1.0.0 不同；比较结果时应固定后端、优化等级和执行引擎。
优化无需保持旧映像逐字节一致。Malbolge20 与原版 Malbolge 不向后兼容。

## 候选产物与验收

初始可移植分发由 `py3-none-any` wheel 与源码归档组成。从源码进行原生编译
仍遵守现有 auto/required/disabled 策略。macOS ARM64 本地原生 wheel 可验证
这条源码路径，不代表已验收配置的完整跨平台原生 wheel 矩阵。

上传前应检查实际归档的版本、README 元数据、源码完整性、RECORD 哈希，
并确认不包含私有研究、环境目录和陈旧原生二进制。在检出目录以外从产物安装，
实际运行文档中的编译/执行命令、Python 回退、可选 IR 与原生执行。
在归档外保留产物哈希与安装回执；源码归档不能包含自身哈希。

单独配置的 TestPyPI 工作流仅面向测试站点。此前试发布成功或本地产物准备
均不代表本版本正式发布。正式上传、Git tag 与 Wiki 修改是分开的动作。

## 正式发布，2026-10-27

[PyPI 1.1.0](https://pypi.org/project/malbolge/1.1.0/) 已提供从合并后主分支提交
构建的 `py3-none-any` 可移植 wheel 与源码归档。两个公开文件的哈希及包介绍
均与已检查的本地产物一致。正式站无缓存安装后，O3、Direct、IR 编译/执行、
字节输入输出及执行预算检查均通过；TUI 扩展使用 Textual 8.2.8 通过无界面
启动、单步与回退检查。主分支质量工作流七个作业及 Pages 构建/部署全部通过。
[发布回执](pypi-1.1.0-publication.json)记录精确产物与源码身份。
原生加速通过源码构建提供，尚未完成的托管原生 wheel 矩阵另行记录。

## 测试站执行，2026-10-27

[TestPyPI 运行 40355946022](https://github.com/Aiaid/pyMalbolge/actions/runs/40355946022)
以 `1.1.0.dev40355946022001` 上传源码归档、可移植 wheel 和 CPython 3.12
manylinux wheel。九组远端安装作业全部通过，包括 Python 3.8、可选 IR、
强制原生源码重建、Windows、Linux x86-64/ARM64 及 macOS Intel/ARM64。
下载的回执、测试站公开文件哈希与构建来源记录一致。

[验收回执](release-1.1.0-acceptance.json)区分已完成的远端检查与原生 wheel
平台矩阵及其实际 JIT 范围。产品质量工作流七项作业全部通过；后续仅修改
CI/helper 的提交未改变安装包内的解释器与编译器模块。
