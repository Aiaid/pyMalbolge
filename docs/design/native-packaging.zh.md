# 原生扩展打包

> [English](native-packaging.md) | **中文**
>
> 状态：源码构建 hook 已实现，发布验收工作流于 2026-10-27 更新。
> 下文本地安装检查及单个平台的托管 Linux TestPyPI 试运行记录日期为
> 2026-10-10。扩展后的 1.1.0 TestPyPI 上传及九个远程安装用例于
> 2026-10-27 全部通过。30 个托管原生 wheel 与 5 个补充本地 macOS ARM64
> wheel 已通过；托管 macOS ARM64 仍在排队。正式 PyPI 发布属于独立步骤。

## 安装行为

项目保留 Hatchling。源码安装在 PEP 517 wheel 构建时调用
`scripts/hatch_native.py`；`scripts/native_build.py` 使用标准 Setuptools
`Extension`/`build_ext` 发现编译器。构建依赖为 Hatchling、Setuptools、wheel，
安装器选择兼容版本。运行时导入与执行不调用编译器。当前原生 VM/JIT
支持 Malbolge20，原版 Malbolge 保留 Python 执行路径。

| 安装输入 | 行为 |
|---|---|
| 匹配的原生 wheel | 安装包内扩展，不需要本机编译器 |
| 纯 Python wheel | 安装 Python 回退版本，不编译原生扩展 |
| sdist 或普通源码目录 | 构建 wheel 并尝试编译原生扩展 |
| Editable 源码目录 | 不自动编译，需要时手动在副本内构建 |

pip 在隔离环境中将源码构建交给 backend；Python 构建依赖不会提供系统
编译器或 SDK。参见 [pip 构建接口](https://pip.pypa.io/en/stable/reference/build-system/)。

## 构建策略

`MALBOLGE_NATIVE_BUILD` 控制构建，不影响已有 wheel 的安装。

| 值 | 规则 |
|---|---|
| `auto`（默认） | 尝试原生；编译失败给出诊断并生成纯 wheel |
| `required` | 编译失败时终止 wheel 构建 |
| `disabled` | 不调用编译器，构建纯 wheel |

源码归档即使在 required 模式也不编译。Editable auto/disabled 不生成原生
代码，required editable 明确报错；editable 副本仍可能加载之前手动构建
的本地扩展。

```sh
uv pip install .
MALBOLGE_NATIVE_BUILD=required uv build --wheel
MALBOLGE_NATIVE_BUILD=disabled uv build --wheel
uv run --with setuptools --with wheel python scripts/build_native_vm.py
```

开发构建器可用 `--output-dir` 和 Unix `--cc`。Windows 使用标准 Visual
Studio 发现；不接受自定义 Windows CC、真正交叉编译或 fat/universal2
扩展产物。不可用的原生构建可在 auto 模式回退；JIT 保持显式选择。

## 新鲜产物与兼容标签

Hook 在全新临时目录编译，通过 Hatch `force_include` 只纳入新二进制。
副本中的 `.so`/`.pyd` 仍排除在 sdist 和 wheel 文件选择之外。sdist 包含
hook/helper、C 源码与 JIT 头文件。Helper 校验源码未在编译中变化，记录
编译命令/版本与指纹，并在构建 worker 中加载新扩展后才接受产物；开发
命令保存构建记录。

原生 wheel 使用非纯包元数据和 CPython/平台 ABI 标签，按构建宿主验证；
当前扩展不是 abi3。纯回退 wheel 为 `py3-none-any`；打包或无效标签错误
不会被吞掉后回退。参见 [Hatch hook](https://hatch.pypa.io/latest/plugins/build-hook/custom/)、
[构建数据](https://hatch.pypa.io/latest/plugins/build-hook/reference/#build-data)及
[Setuptools 扩展](https://setuptools.pypa.io/en/latest/userguide/ext_modules.html)。

macOS 未设置 ARCHFLAGS 时，仅在 worker 默认选择运行宿主的单架构；保留
显式用户参数。支持使用 universal2 Python 构建宿主单架构扩展：新产物的
真实薄 Mach-O 决定架构标签，标准 wheel 工具检查部署版本。真正的 fat
扩展、非宿主 slice 及不受支持的目标覆盖会被拒绝，避免标签误标。

## GitHub Actions 预构建

`.github/workflows/native-wheels.yml` 使用 cibuildwheel 4.3.0，五个原生
runner 覆盖 Linux x86-64/ARM64、macOS Intel/ARM64、Windows x86-64，
不使用模拟器。默认 macOS ARM64 job 使用 `macos-15`。当前标签和资源可用性见
[GitHub runner 说明](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)。

| 触发/job | 配置覆盖 |
|---|---|
| 相关 pull request | CPython 3.12，共七个 wheel，含 Linux 两种 libc |
| 版本标签或完整手动触发 | CPython 3.9–3.13，同五个 runner 共 35 个 wheel |
| 独立兼容 job | Ubuntu 上 CPython 3.8 原生/纯源码 wheel 安装及策略检查 |

手动触发时，可设置 `macos_arm64_only=true` 仅重试五个 macOS ARM64 wheel，
不重建已完成的其他组及 Python 3.8 job。`macos_arm64_runner` 可为该组选择
`macos-15`（默认）或 `macos-26`。

3.8 Linux 产物是兼容检查，不是 manylinux 发布 wheel。原生构建使用
required 模式。cibuildwheel 修复 Linux manylinux/musllinux wheel，在
临时目录测试安装后的包，产物附件保留 14 天；工作流不发布 PyPI。参见
[cibuildwheel 选项](https://cibuildwheel.pypa.io/en/v4.3.0/options/)。

`scripts/verify_native_install.py` 拒绝副本导入及缺失 required 原生扩展，
检查 wheel 元数据/默认选择、原版 Python I/O/EOF、原生字节 I/O/EOF/预算、
COW/页面及自修改。Linux ARM64 必须实际执行 JIT 机器码；macOS ARM64
通过独立 ctypes 调用 `pthread_jit_write_protect_supported_np()`，要求其
结果与原生 JIT 能力报告一致：可用时必须实际执行机器码并通过自修改
一致性检查；不可用时必须拒绝显式 `engine="jit"`。原生写保护守卫保持
启用。x86-64 job 验证显式 JIT 不可用错误。参见 [JIT 能力契约](native-jit.zh.md)。
每个安装后的 wheel 还运行 `scripts/verify_release_install.py`：分发元数据
和 `malbolge.__version__` 必须与副本 `pyproject.toml` 读取的候选版本一致。
这个仅依赖标准库的 helper 通过默认 O3 和显式 Direct 编译小型 Hello
程序，以有界 Python VM 执行两份产物，检查自动 VM 选择，并检查原版
Malbolge 字节 I/O 和 CLI 预算退出码。它拒绝副本导入，记录已安装模块和
生成镜像的指纹。独立 Python 3.8 原生与纯包安装也都运行两个 helper。

发布报告使用含解释器、平台及 Linux libc 家族的 cibuildwheel 构建标识，
文件名前缀与 VM 报告分开。Linux smoke 报告显式挂载到宿主，容器失败时
也保留 JSON。CI 保存提交/解释器/模块指纹、wheel 标签及产物指纹。编译命令/版本记录
目前由开发构建器保存，成功 hook 构建不把该记录归档进 CI JSON；构建
失败会输出 backend 诊断。

## TestPyPI 试发布管线

`.github/workflows/testpypi.yml` 可手动触发，也在
`codex/testpypi-native-ci` 分支推送时运行。它仅在临时 CI 副本中将分发和
模块版本同步写为唯一的 `1.1.0.dev<run-id-and-attempt>` 开发版本，构建并
测试一个 required 原生 CPython 3.12 manylinux x86-64 wheel，随后关闭原生
编译，构建 `py3-none-any` wheel 和 sdist。三份分发产物都通过元数据检查、
记录 SHA-256 指纹并上传 TestPyPI。仓库的稳定版本号保持不变。

九个远程安装 job 覆盖以下配置：

| 原生 runner | Python | TestPyPI 分发产物 / 扩展依赖 |
|---|---|---|
| Linux x86-64 | 3.8 | 纯 wheel |
| Linux x86-64 | 3.10 | 纯 wheel，加固定版本的可选 IR 依赖 |
| Linux x86-64 | 3.12 | 原生 wheel |
| Linux x86-64 | 3.13 | 纯 wheel |
| Linux ARM64 | 3.12 | 纯 wheel |
| macOS ARM64 | 3.12 | 纯 wheel |
| macOS Intel | 3.12 | 纯 wheel |
| Windows x86-64 | 3.12 | 纯 wheel |
| Linux x86-64 | 3.12 | sdist，required 原生源码构建 |

各 job 不检出源码，在全新环境中核对复制的 helper 与构建提交、运行、版本
身份及已记录指纹，再关闭缓存，按精确版本和强制产物指纹从 TestPyPI 安装。
Wheel job 强制使用二进制分发；源码 job 选择 sdist 并要求成功编译。
源码构建和 IR 依赖在独立步骤从正式 PyPI 安装；项目分发仅从 TestPyPI
获取。源码 job 预装构建依赖，并在显式 sdist 构建时关闭构建隔离。

两个安装检查 helper 在所有远程 job 中运行。发布检查覆盖 O3/Direct 编译及
有界执行、版本身份、字节 I/O 和预算；IR job 还通过显式 IR backend 编译
并执行。VM helper 检查要求的原生或纯包安装契约。这里的远程 ARM job
安装纯 wheel；原生 ARM/JIT 验收由上文 35 个 wheel 的工作流负责。
构建和各安装 job 的记录作为 Actions 附件保留 14 天。

只有隔离的发布 job 接收 GitHub Actions 仓库加密 Secret
`TEST_PYPI_API_TOKEN`；该 job 不检出源码，明确使用
`https://test.pypi.org/legacy/`，凭据缺失会在上传前失败；工作流没有配置
正式 PyPI 上传。参见[历史托管试发布证据](../notes/testpypi-ci-validation.json)。

## 验收与剩余边界

2026-10-10 的本地检查显示，默认模式 sdist 安装自动构建原生扩展；CPython 3.8.19、3.12.9、
3.13.14 原生 wheel 通过干净环境中的 native/JIT 检查，纯 wheel 通过
Python 回退检查。策略、RECORD、源码完整、旧二进制排除及源码重建测试
通过，矩阵身份与工作流语法已本地检查。这不是托管跨平台验收，也没有
新增性能 benchmark。

[打包验收](../notes/native-packaging-validation.json)与 TestPyPI 试运行记录
上述带日期的检查，包括托管 Linux x86-64 CPython 3.12 原生构建及安装 smoke。

[扩展 TestPyPI 验收运行](https://github.com/Aiaid/pyMalbolge/actions/runs/40355946022)
于 2026-10-27 在提交 `f781b45` 通过：三份分发产物以
`1.1.0.dev40355946022001` 上传，九个远程安装用例全部通过，下载复核的
九份 `release.json` 也全部记录成功。它覆盖上表配置中的源码、纯包、原生
及可选 IR 安装。

提交 `5ba394b` 的[产品 QoS 运行](https://github.com/Aiaid/pyMalbolge/actions/runs/40355389398)
七个 job 全部通过。从该提交到 `b7b36ed` 的变更仅涉及 CI 配置、验证 helper
和文档。

较早的[原生矩阵运行](https://github.com/Aiaid/pyMalbolge/actions/runs/40355942641)
因 macOS ARM64 的系统报告不支持线程局部 JIT 写保护而未满足 JIT 要求。
当前 helper 显式核对该系统能力，并保留原生守卫。

提交 `e97edc2` 的[原生覆盖运行](https://github.com/Aiaid/pyMalbolge/actions/runs/40356927572)
已完成 Linux x86-64/ARM64、macOS Intel、Windows x86-64 四个平台的 30 个
wheel。30 份产物指纹、30 份 VM 报告及 30 份发布报告均已复核；Python 3.8
原生/纯包兼容检查也通过。十个 Linux ARM64 用例各实际执行至少 4,096 个
JIT 步。剩余 macOS ARM64 组排队超过十分钟后，在提交 `b7b36ed` 以
`macos-26` 启动[定向 ARM64 重试](https://github.com/Aiaid/pyMalbolge/actions/runs/40358838205)，
当前仍在排队。完整 35 个托管原生 wheel 的验收仍待完成。

补充本地 macOS 27.0.1 ARM64 检查中，CPython 3.9–3.13 五个版本全部通过。
各 wheel 均从固定指纹的 1.1.0 sdist 构建，在全新环境安装并通过两个 helper，
启用原生写保护守卫，各实际执行 4,096 个 JIT 步。`malbolge/` 下全部 58 个
源码文件与固定 sdist 一致。CPython 3.12 扩展的 Mach-O 最低系统为 11.0，
其余四份为 26.0；在 macOS 27.0.1 上执行确立该本地系统的验收结果，旧系统
及最低系统版本的运行验收仍未验证。

[1.1.0 验收记录](../notes/release-1.1.0-acceptance.json)保存九个 TestPyPI 用例、
30 个托管 wheel、五个本地 wheel 及仍待完成的托管 macOS ARM64 范围。
原版原生引擎、一般 JIT 发射器及 PyPI 分发属于独立 roadmap 项。

pip 可能缓存纯回退 wheel，之后已有编译器仍继续复用。已有 wheel 的
安装不会调用 build hook，改变构建模式也不会重建；需要原生时应明确从
源码重建。同版本发布的纯 wheel 也可能直接满足未覆盖平台而不尝试
sdist。参见 [pip 可选扩展缓存说明](https://pip.pypa.io/en/stable/topics/caching/#avoiding-caching)。
