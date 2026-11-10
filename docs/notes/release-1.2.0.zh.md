# 1.2.0 正式发行冻结

> [English](release-1.2.0.md) | **中文**
>
> 冻结核对日期：2026-11-10。正式版本：**1.2.0**。
> 最终源码提交/产物验收及正式发布仍待完成；已记录的正式发行仍为 1.1.0。

正式版编译器/VM 实现冻结于 rc2 提交
`063a3c59efaa1de4545e59bd0a26ee68dfddf860`，不纳入开发副本中未提交的实验 JIT
修改。正式版本元数据、发行门槛及文档需要新提交和重新构建的产物，不能将 rc2
回执改称正式版验收。

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

[运行 42757794922](https://github.com/Aiaid/pyMalbolge/actions/runs/42757794922)
在 rc2 提交 `063a3c59` 成功，发布 **1.2.0rc2.dev42757794922001**。
全部 **37** 个公开下载与已验收哈希匹配：**35 个原生 wheel**（CPython 3.9–3.13，
Linux glibc/musl x86-64/ARM64、macOS Intel/ARM64、Windows x86-64），另加便携
wheel 和 sdist。**13 组远端安装/输入检查**与**七个同提交质量 CI 作业**全部通过。
Python 3.8 源码 wheel 兼容性检查与这 35 个 wheel 矩阵分开记录。

详见 [rc2 回执](release-1.2.0rc2-testpypi.json)和
[测试项目页](https://test.pypi.org/project/malbolge/1.2.0rc2.dev42757794922001/)。
较早的 [rc1 回执](release-1.2.0-testpypi.json)对应 `a466170`、三个产物与九组
安装；[本地候选验证](release-1.2.0-validation.json)同样保持为未改写的历史证据。
相互重叠的测试批次不可相加。

### 平台与 JIT 边界

- macOS ARM64 deployment target、wheel 标签及 Mach-O 最低系统均为 **15.0**。
  托管执行仅在 **15.8.2** 完成，精确 15.0 运行兼容性尚未测试；元数据一致不等于
  最低系统执行证明。
- 托管 Mac JIT 不可用，保持写保护守卫并按契约拒绝；这是原生 VM 验收，不是
  托管 Mac JIT 执行验收。
- 十个 Linux ARM64 libc/ABI wheel 均实际执行 NOP JIT 机器码。既有本地 Mac/CM4
  检查只证明对应设备执行。JIT 仍为显式实验功能，以上均不构成普遍提速结论。

## 安装已记录的 TestPyPI 候选

在源码检出之外的新目录中操作。以下固定安装已记录的 rc2 测试快照，不是正式
1.2.0 或正式站发行：

```sh
uv venv
uv pip install --index-url https://test.pypi.org/simple/ --no-deps 'malbolge==1.2.0rc2.dev42757794922001'
uv run --no-project python -c "import malbolge; print(malbolge.__version__)"
```

输出版本必须为 `1.2.0rc2.dev42757794922001`。基础包没有运行时依赖。可选依赖另从
正式 PyPI 安装，不重新安装项目，也不混用索引：

```sh
uv pip install --index-url https://pypi.org/simple/ 'textual>=0.40.0'
# 可选 IR 仅适用于 Python 3.10+：
uv pip install --index-url https://pypi.org/simple/ 'xdsl==0.69.0'
```

匹配的平台/CPython ABI 可选择原生 wheel，否则可使用便携 wheel。精确审计应
核对回执中的文件名和哈希。`pyproject.toml` 将 `docs/notes/pypi-description.md`
嵌入分发元数据；README 修改不会改变已经上传的包介绍。

## 正式发布门槛

正式工作流 `.github/workflows/pypi.yml` 要求最终源码提交的质量检查、完整
**37 文件**构建及 **13 组上传前安装包/输入检查**通过后才上传，发布还需要有效
正式凭据。上传后须核对每个公开产物的哈希，并通过 **13 组远端安装/输入检查**。
已配置或排队中的门槛不等于通过；缺少凭据或门槛失败不能报告为发布成功。

本文尚未记录最终源码 SHA、正式产物哈希和正式站执行验收。后续状态见
[正式发布 Actions](https://github.com/Aiaid/pyMalbolge/actions/workflows/pypi.yml)及
[正式项目页](https://pypi.org/project/malbolge/)。必须重新构建并验收精确正式产物，
不能复用 rc2 哈希。精确 macOS 15.0 运行测试仍是单独披露的缺口，不能声称
15.8.2 托管执行或元数据一致已满足先前提出的最低系统执行要求。

本维护发行冻结不包含新布局协议、直接 semantic→LAL 后端、一般 Python 支持或
新的性能提升声明。
