# 1.2.0 正式发行

> [English](release-1.2.0.md) | **中文**
>
> 发布核对日期：2026-11-10。

**[1.2.0 已发布到正式 PyPI](https://pypi.org/project/malbolge/1.2.0/)。**
源码提交：`65c44bf7ee112f0df8c85b64b1c826787713492b`。
[正式运行 42782746293](https://github.com/Aiaid/pyMalbolge/actions/runs/42782746293)
通过 GitHub OIDC Trusted Publishing 上传 35 个原生 wheel、一个便携 wheel 和
一个 sdist。全部 37 个公开产物哈希、七个同提交质量 CI 作业及 13 组上传前
安装/输入检查通过。上传后 13 组远端安装/输入检查也全部通过；最终各组结果及精确产物身份见
[正式发布回执](pypi-1.2.0-publication.json)。

发行编译器/VM 保留 rc2 基线，未发布未提交的实验 JIT 修改。
[rc2 回执](release-1.2.0rc2-testpypi.json)保留为独立历史证据，不替代
正式产物检查。macOS ARM64 的 deployment target、标签与 Mach-O 最低系统为
15.0，精确 macOS 15.0 运行兼容性仍未测试。rc2 及正式版五个 ARM64 ABI 的实际宿主均为 15.8.2。正式托管 Mac JIT 不可用，
保留守卫并显式拒绝；Linux ARM64 NOP JIT 执行为另一项证据。本地
Mac/CM4 执行只证明对应设备，不构成普遍提速结论。

## 为什么另开版本

已下载正式 1.1.0 的可移植 wheel、Linux CPython 3.12 原生 wheel 和源码包，
并与原发布记录逐项核对 SHA-256。两个 wheel 只有项目自身 LICENSE，未带入
移植编译器各阶段所需的 Nagoya 原文版权与许可声明。源码包还包含一组来源
README 标明 GPL-3.0 的可选 HeLL 测试夹具。这是分发内容检查结果，不等于
全部运行功能有问题，也不是对整个项目作笼统的法律判断。

1.2 候选补齐声明并收紧源码包范围。1.1.0 原发布文件保持不变，其历史发布
回执只适用于原文件。

## 发行变更

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
  历史 rc2 托管执行仅在 **15.8.2** 完成，精确 15.0 运行兼容性尚未测试；元数据一致不等于
  最低系统执行证明。
- 托管 Mac JIT 不可用，保持写保护守卫并按契约拒绝；这是原生 VM 验收，不是
  托管 Mac JIT 执行验收。
- 十个 Linux ARM64 libc/ABI wheel 均实际执行 NOP JIT 机器码。既有本地 Mac/CM4
  检查只证明对应设备执行。JIT 仍为显式实验功能，以上均不构成普遍提速结论。

## 安装正式 1.2.0

在源码检出之外的新目录中，从正式 PyPI 安装精确版本：

```sh
uv venv
uv pip install --index-url https://pypi.org/simple/ 'malbolge==1.2.0'
uv run --no-project python -c "import malbolge; print(malbolge.__version__)"
```

输出应为 `1.2.0`。下方 TestPyPI 命令仅用于复现历史 rc2。

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

## 正式发布与验证

最终源码提交为 `65c44bf7ee112f0df8c85b64b1c826787713492b`。
[正式运行 42782746293](https://github.com/Aiaid/pyMalbolge/actions/runs/42782746293)
通过七个同提交质量 CI 作业，构建完整 **37 文件**产物包，并通过 **13 组上传前
安装包/输入检查**。通过 GitHub OIDC Trusted Publishing、使用 `pypi` 环境
成功上传 PyPI，不使用长期正式 API token。该环境自动创建，尚未独立验证
分支/环境保护配置。

CI 已通过全部 **37 个公开产物哈希**验证。上传后 **13 组远端安装/输入检查也全部通过**。最终结果、哈希和实际
宿主证据见[正式发布回执](pypi-1.2.0-publication.json)。精确 macOS 15.0 运行测试
仍未完成；rc2 的 15.8.2 执行及元数据一致不等于先前最低系统执行要求已满足。

后续正式工作流计划改为仅手动触发，避免普通推送重试不可覆盖的 1.2.0 上传。
触发前核对当前[正式工作流](https://github.com/Aiaid/pyMalbolge/actions/workflows/pypi.yml)。
新发行需要新版本与自己的验收。本维护发行不包含新布局协议、直接 semantic→LAL
后端、一般 Python 支持或普遍提速声明。
