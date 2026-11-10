# pyMalbolge

将 Python 子集编译为 **Malbolge20**，运行原版 Malbolge 或 Malbolge20 程序，
并通过 CLI/TUI 调试器检查执行过程。

- Python 编译器支持 C 与直连后端、O0–O3 控制，O3 自动选择适用的 Direct/语义 IR 候选。
- `ir` 扩展提供可选语义 IR 工具（Python 3.10+）。
- 面向字节的解释器，批处理支持执行步数及输出预算。
- 可选原生 Malbolge20 批处理执行，缺失时回退到 Python。
- 调试器支持断点、监视点、回退和内存检查。

编译器与 Python 解释器没有必需的 Python 运行时依赖；可选 TUI 使用 Textual。
这是 Python 子集编译器，不能编译任意 Python 程序。

## 安装

基础包需要 Python 3.8 或更新版本。即使本说明显示在 TestPyPI，下列命令也从
**正式 PyPI** 安装：

```sh
uv venv
uv pip install malbolge
# 可选界面与 IR 工具：
uv pip install 'malbolge[tui]'
uv pip install 'malbolge[ir]'  # Python 3.10+
```

安装 **TestPyPI 候选**时，使用独立环境，并将 `<exact-test-version>` 替换为
该版本页面上显示的精确版本：

```sh
uv venv
uv pip install --index-url https://test.pypi.org/simple/ --no-deps 'malbolge==<exact-test-version>'
uv run --no-project python -c "import malbolge; print(malbolge.__version__)"
```

基础包没有运行时依赖，因此有意使用 `--no-deps`。测试 TUI 或 IR 时，分别从
正式 PyPI 安装 `textual>=0.40.0` 或 `xdsl==0.69.0`；xDSL 需要 Python 3.10+。
保留项目的测试版本固定值，不让混合索引替你选择版本。测试站上传不等于正式发布。

纯 Python wheel 无需 C 编译器即可运行。从源码构建时，默认尝试构建原生扩展，
编译不可用则回退到 Python。`MALBOLGE_NATIVE_BUILD=disabled` 禁止原生编译；
`required` 在编译失败时终止构建。安装后的包在导入或执行时不会启动编译器。
可编辑安装跳过原生编译；若源码检出需要原生执行，应手动构建扩展。

原生 wheel 是否可用取决于具体发行版、OS、架构及 CPython ABI，应查看该版本的
**Download files** 列表。便携 wheel 不证明对应平台支持原生或 JIT。Malbolge20
批处理默认使用可加载的原生扩展，否则回退 Python；原版 Malbolge 和调试器仍使用
Python。ARM64 JIT 是显式启用、受平台条件限制的实验，绝不自动选择。详见
[发行及平台证据](https://github.com/Aiaid/pyMalbolge/blob/master/docs/current-status.zh.md)。

## 编译与运行

保存为 `hello.py`：

```python
print("Hello, world!")
```

在安装了该包的环境中执行：

```sh
uv run --no-project python -m malbolge compile hello.py --no-cache -o hello.mb
uv run --no-project python -m malbolge --variant=malbolge20 hello.mb --engine=python --input '' --max-steps 5000000 --max-output 64
# Hello, world!
```

编译默认采用 O3 自动选择。基础安装无需 xDSL 即可使用直连路径；可选 `ir`
扩展启用适用的语义 IR 候选。显式使用 `--backend=c`、`--backend=direct`
或 `--backend=ir` 可选定对应路径。

Malbolge20 使用 20-trit 字长，与原版 10-trit Malbolge **不向后兼容**。
Python 编译器的输出目标是 Malbolge20。

## 试用浏览器调试器

[打开在线调试器](https://aiaid.github.io/pyMalbolge/)，无需安装即可单步运行
**原版 Malbolge**。浏览器调试器不能编译 Python 或执行 Malbolge20 程序。

## 文档与归属

包介绍在各分发文件构建时嵌入。`master` 源码文档可能描述更新的工作；复现已安装
包时，应以相应版本、分发文件和带日期的验收记录为准。

- [源码及详细用法](https://github.com/Aiaid/pyMalbolge)
- [Python 子集规格](https://github.com/Aiaid/pyMalbolge/blob/master/docs/specs/python-subset-spec.zh.md)
- [报告问题](https://github.com/Aiaid/pyMalbolge/issues)
- [Malbolge20 项目](https://malbolge20.gitlab.io/index-en.html)
- [上游编译工具链](https://gitlab.com/malbolge20/malbolge20_creator)

pyMalbolge 最初分叉自
[Avantgarde95/pyMalbolge](https://github.com/Avantgarde95/pyMalbolge)。
编译器包含 Nagoya University Malbolge20 工具链组件的 Python 移植，
并加入 Python 前端和额外工具。源码保留上游归属和适用声明。
pyMalbolge 以 MIT 许可证分发。
