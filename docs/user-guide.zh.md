# 源码工作区用户指南

> [English](user-guide.md) | **中文**
>
> 核对日期：2026-11-13。下述 MG 命令和实验是已整合的源码改动，
> 不表示已经包含在正式 PyPI 1.2.0 产物中。

## 准备与执行

从仓库根目录运行。基础包需要 Python 3.8+；可选 IR 工具需要 Python 3.10+
及固定版本的 xDSL。

```sh
uv sync --extra dev --extra ir
uv run --no-sync python -m malbolge compile --help
uv run --no-sync python -m malbolge compile-mg --help
```

Original Malbolge、调试器和旧式流执行仍使用 Python。Malbolge20 批处理默认
`auto`：优先加载 native，否则回退 Python。对照实验应明确选择
`--engine python` 或 `--engine native`。

## 手写 MG

工作区自带的这个夹具输出 `Hi`：

```sh
uv run --no-sync python -m malbolge compile-mg test/fixtures/nagoya/mg_b_hi.mg --emit-mc demo.mc -o demo.mb --stats
uv run --no-sync python -m malbolge --variant=malbolge20 demo.mb --engine python --input '' --max-steps 3000000 --max-output 16
```

`compile-mg` 不依赖 C 编译器、外部名古屋工具、Perl 或 xDSL。没有输出选项时
向 stdout 输出 MC；`--emit-mc -` 和 `-o -` 显式选择 stdout，两个产物只能有
一个使用它。默认值为 `--op-style cluster --jmp-style main --target-pipeline structured`，
对应可选值分别为 `inline`、`direct` 和 `text`。

输入为 UTF-8，拒绝源文件/输出别名及重复输出路径。替换对**单个文件**具有原子性，
不是两个产物的整体事务；stdout 无法回滚。诊断与 JSON 指标写入 stderr。
编译/I/O 错误退出 1，参数错误退出 2，中断退出 130。Python 前端的优化等级和
编译缓存不适用于这个命令。详见 [MG 规范](specs/mg-spec.zh.md)。

## Native 与 JIT 验收

```sh
uv run --no-sync --with setuptools --with wheel python scripts/build_native_vm.py
uv run --no-sync python -c "from malbolge import native; assert native.native_available(); print(native.jit_available())"
uv run --no-sync python -m pytest test/test_native_vm.py test/test_native_jit.py -q -rs
```

Native 需要宿主 C 编译器；Windows 使用标准 Visual Studio 工具发现。
JIT 仍需显式选择，属于实验功能：当前只有针对受支持的小端 Linux/macOS ARM64
的带保护 NOP 发射器。Windows AMD64 可执行 native 不代表支持 JIT；该平台明确
拒绝 JIT 请求。macOS 还取决于运行时保护能力探测。

本候选分支的验证见[限定范围回执](notes/reliability-mg-candidate-validation.json)。
包含其他实验的整合分支所取得的全量测试及 wheel 结果，不是本候选分支的验收结果。
远程 CI 与真实浏览器布局仍未验证。
