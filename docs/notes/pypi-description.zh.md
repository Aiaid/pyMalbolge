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

需要 Python 3.8 或更新版本：

```sh
uv venv
uv pip install malbolge
# 可选界面与 IR 工具：
uv pip install 'malbolge[tui]'
uv pip install 'malbolge[ir]'  # Python 3.10+
```

纯 Python wheel 无需 C 编译器即可运行。从源码构建时，默认尝试构建原生扩展，
编译不可用则回退到 Python。`MALBOLGE_NATIVE_BUILD=disabled` 禁止原生编译；
`required` 在编译失败时终止构建。安装后的包在导入或执行时不会启动编译器。
可编辑安装跳过原生编译；若源码检出需要原生执行，应手动构建扩展。

## 编译与运行

保存为 `hello.py`：

```python
print("Hello, world!")
```

在安装了该包的环境中执行：

```sh
uv run python -m malbolge compile hello.py --no-cache -o hello.mb
uv run python -m malbolge --variant=malbolge20 hello.mb --engine=python --input '' --max-steps 5000000 --max-output 64
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
