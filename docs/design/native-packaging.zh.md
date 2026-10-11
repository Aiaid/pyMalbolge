# 原生扩展打包

> [English](native-packaging.md) | **中文**
>
> 状态：源码构建 hook 与 wheel CI 配置已实现，2026-10-10。
> 本地 macOS ARM64 安装检查通过；托管 Linux、Windows、macOS Intel
> 矩阵尚未运行，原生 wheel 尚未发布到 PyPI。

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
不使用模拟器。当前标签和资源可用性见
[GitHub runner 说明](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)。

| 触发/job | 配置覆盖 |
|---|---|
| 相关 pull request | CPython 3.12，共七个 wheel，含 Linux 两种 libc |
| 版本标签或手动触发 | CPython 3.9–3.13，同五个 runner 共 35 个 wheel |
| 独立兼容 job | Ubuntu 上 CPython 3.8 原生/纯源码 wheel 安装及策略检查 |

3.8 Linux 产物是兼容检查，不是 manylinux 发布 wheel。原生构建使用
required 模式。cibuildwheel 修复 Linux manylinux/musllinux wheel，在
临时目录测试安装后的包，产物附件保留 14 天；工作流不发布 PyPI。参见
[cibuildwheel 选项](https://cibuildwheel.pypa.io/en/v4.3.0/options/)。

`scripts/verify_native_install.py` 拒绝副本导入及缺失 required 原生扩展，
检查 wheel 元数据/默认选择、原版 Python I/O/EOF、原生字节 I/O/EOF/预算、
COW/页面及自修改。ARM job 必须实际执行 JIT，其他 job 验证显式 JIT
不可用错误。Linux smoke 报告显式挂载到宿主，容器失败时也保留 JSON。
CI 保存提交/解释器/模块指纹、wheel 标签及产物指纹。编译命令/版本记录
目前由开发构建器保存，成功 hook 构建不把该记录归档进 CI JSON；构建
失败会输出 backend 诊断。

## TestPyPI 试发布管线

`.github/workflows/testpypi.yml` 可手动触发，也在
`codex/testpypi-native-ci` 分支推送时运行。它构建并测试一个 required 原生
CPython 3.12 manylinux x86-64 wheel，只在临时 CI 副本写入唯一开发版本，
上传 TestPyPI，随后在全新环境从 TestPyPI 安装精确版本并重跑原生 smoke。
仓库的稳定版本号保持不变。

只有隔离的发布 job 接收 GitHub Actions 仓库加密 Secret
`TEST_PYPI_API_TOKEN`；该 job 不检出源码，明确使用
`https://test.pypi.org/legacy/`，凭据缺失会在上传前失败。构建与安装记录
保存指纹和版本身份；工作流没有配置正式 PyPI 上传。参见
[托管试发布证据](../notes/testpypi-ci-validation.json)。

## 验收与剩余边界

本地默认模式 sdist 安装已自动构建原生扩展；CPython 3.8.19、3.12.9、
3.13.14 原生 wheel 通过干净环境中的 native/JIT 检查，纯 wheel 通过
Python 回退检查。策略、RECORD、源码完整、旧二进制排除及源码重建测试
通过，矩阵身份与工作流语法已本地检查。这不是托管跨平台验收，也没有
新增性能 benchmark。

[打包验收](../notes/native-packaging-validation.json)记录当前检查。
TestPyPI 试运行已通过托管 Linux x86-64 CPython 3.12 原生构建和安装 smoke；
其余 Linux 矩阵、Windows/MSVC 与 macOS Intel 执行仍待托管验收。原版原生引擎、一般 JIT 发射器
及 PyPI 分发属于独立 roadmap 项。

pip 可能缓存纯回退 wheel，之后已有编译器仍继续复用。已有 wheel 的
安装不会调用 build hook，改变构建模式也不会重建；需要原生时应明确从
源码重建。同版本发布的纯 wheel 也可能直接满足未覆盖平台而不尝试
sdist。参见 [pip 可选扩展缓存说明](https://pip.pypa.io/en/stable/topics/caching/#avoiding-caching)。
