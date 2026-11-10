# 1.2.0 候选版本

> [English](release-1.2.0.md) | **中文**
>
> 准备日期：2026-11-10。下一个源码候选：**1.2.0rc2**。
> 先前 TestPyPI 候选 **1.2.0rc1.dev42754363710001** 已通过下述限定范围的远端检查。
> 正式 PyPI 仍为 1.1.0，未执行正式发布。

下个候选正在加入额外输入实验及同提交原生 wheel 矩阵；本文尚不将这些检查标为
通过。下方 rc1 证据始终对应 `a466170` 及其精确产物哈希，不代表 rc2 或最终
1.2.0 包已经通过。

## 为什么另开版本

已下载正式 1.1.0 的可移植 wheel、Linux CPython 3.12 原生 wheel 和源码包，
并与原发布记录逐项核对 SHA-256。两个 wheel 只有项目自身 LICENSE，未带入
移植编译器各阶段所需的 Nagoya 原文版权与许可声明。源码包还包含一组来源
README 标明 GPL-3.0 的可选 HeLL 测试夹具。这是分发内容检查结果，不等于
全部运行功能有问题，也不是对整个项目作笼统的法律判断。

1.2 候选补齐声明并收紧源码包范围。1.1.0 原发布文件保持不变，其历史发布
回执只适用于原文件。

## 候选变更

- wheel 与源码包包含 `THIRD_PARTY_NOTICES.md`、四份逐字保留的上游 MIT
  许可文本，以及相应 `License-File` 元数据。
- 源码分发排除可选 HeLL/LMAO 夹具及依赖该夹具的测试；仓库中的研究文件保留。
- 把 Direct 编译器中的共享 AST 源码分析抽成无第三方依赖模块，由 Direct
  和语义前端共同使用，保持原有源码检查和代码生成行为。
- 可选 IR CI 纳入共享分析测试；打包测试验证许可文本原文、排除规则、wheel
  RECORD 与安装后执行。
- 打包验收保留调用者指定的 C 编译器。
- TestPyPI 临时版本脚本支持保留 alpha、beta、rc 身份及重试，例如将
  `1.2.0rc1` 标为临时工作区中的 `1.2.0rc1.dev<运行及重试编号>`。
- 更新实现与发布边界，不把历史 benchmark 当作本候选的性能数据。

## TestPyPI 验收

[运行 42754363710](https://github.com/Aiaid/pyMalbolge/actions/runs/42754363710)
从独立 `codex/release-1-2-0-testpypi` 分支的提交 `a466170` 构建并发布三个包。
九组远程安装全部通过：Linux Python 3.8、3.10 加 IR、3.12 原生、3.13，
Linux ARM64 纯 Python、macOS ARM64 与 Intel 纯 Python、Windows 纯 Python，
以及 Linux 源码包现场构建原生扩展。七个质量 CI 作业也全部通过。
已下载测试站三个实际文件，与 CI 构建哈希核对一致，并复验许可及分发边界。

详见 [TestPyPI 回执](release-1.2.0-testpypi.json) 和
[测试项目页](https://test.pypi.org/project/malbolge/1.2.0rc1.dev42754363710001/)。
这些结果不代表正式发布，也不代表 Apple Silicon 原生或 JIT 验收。
下方本地回执保留先前未发布阶段的历史状态，不将其改称远程验收结果。

## 安装已记录的 TestPyPI 候选

在源码检出之外的新目录中操作。下列命令固定已经记录的 rc1 快照，不安装下个
候选或正式 PyPI 包：

```sh
uv venv
uv pip install --index-url https://test.pypi.org/simple/ --no-deps 'malbolge==1.2.0rc1.dev42754363710001'
uv run --no-project python -c "import malbolge; print(malbolge.__version__)"
```

输出版本必须为 `1.2.0rc1.dev42754363710001`；测试后续候选时换用新回执中的精确
版本。基础包没有运行时依赖。可选依赖另从正式 PyPI 安装，不重新安装项目，也不
混用索引：

```sh
uv pip install --index-url https://pypi.org/simple/ 'textual>=0.40.0'
# 可选 IR 仅适用于 Python 3.10+：
uv pip install --index-url https://pypi.org/simple/ 'xdsl==0.69.0'
```

匹配的 CPython 3.12 Linux x86-64 环境可选中 rc1 原生 wheel；其他平台可选择便携
wheel，这不代表这些平台原生验收通过。精确产物审计应使用回执中的文件名和哈希，
不能仅靠版本约束。

`pyproject.toml` 将 `docs/notes/pypi-description.md` 嵌入包索引介绍，中文文件是
配套翻译。修改 GitHub README 不会改变已有 TestPyPI/PyPI 页面，更新元数据需要
新的分发文件。rc1 之后的介绍修改用于下个候选，不追溯修改已经记录的上传。

## 验证与未完成门槛

最终本地命令、产物身份、安装检查及适用范围见[候选验证记录](release-1.2.0-validation.json)。
相互重叠的测试批次不可相加。

尚未完成跨平台发布。正式发布前仍需：

1. 确定最终正式版本及提交，从该精确提交重建并复验产物；TestPyPI 结论仅
   覆盖回执记录的字节。
2. 补齐已测 Linux CPython 3.12 以外的原生 OS/ABI 矩阵；纯 Python wheel
   跨平台通过不代表对应原生构建通过。
3. Apple Silicon wheel 继续等待 deployment target、wheel tag、Mach-O 最低
   系统及真实最低 OS 执行核对，不提前发布。
4. ARM64 JIT 保持显式实验功能；x86-64 拒绝不支持 JIT 的测试不能代替
   ARM64 机器码验收。
5. 完成正式版本检查并取得发布授权。

本维护候选不包含新布局协议、直接 semantic→LAL 后端、一般 Python 支持或
新的性能提升声明。
