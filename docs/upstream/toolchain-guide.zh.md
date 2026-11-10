# 工具链构建与复现指南

> [English](toolchain-guide.md) | **中文**

> **注(P4 之后)**:编译 Python/C/.mg 程序已**不需要**本文档的任何
> 外部工具——`malbolge/compiler/` 的纯 Python 移植覆盖了全链
> (`python3 -m malbolge compile prog.py -o prog.mb`)。本文档保留给
> 受控参考移植对照、独立执行检查与上游考古。中间产物逐字节相同、填充确定性
> 和源程序正确性是三类不同的结论。
>
> 外部参考工具的获取、构建与使用,含全部已踩过的平台坑
>(macOS/Darwin 实测)。工具本体均在 gitignore 的 `ref/` 下,不入库。

## 0. 当前上游与冻结参考的区别

[官方主页](https://malbolge20.gitlab.io/index-en.html)指向
[GitLab.com 整合 creator 仓库](https://gitlab.com/malbolge20/malbolge20_creator)。
本文最后复现的源码版本为
[`2b42f4817afecca6b4c4f7374e21a399b6488e31`](https://gitlab.com/malbolge20/malbolge20_creator/-/tree/2b42f4817afecca6b4c4f7374e21a399b6488e31)
（提交日期 2026-10-06，2026-10-26 核验），**不声称它是今天的 main**。
它已有 `mbcc` 驱动、Python `parse_mc2.py`、种子控制与地址搜索缓存，不能再当作
旧五仓、仅 Perl 的工具链。对照新上游时应使用该版本自己的 README/构建说明。

```bash
git clone https://gitlab.com/malbolge20/malbolge20_creator ref/malbolge20_creator
git -C ref/malbolge20_creator checkout 2b42f4817afecca6b4c4f7374e21a399b6488e31
```

在该次复现版本中：

- `mbcc --seed N` 同时控制 ternary 与初始化器种子，初始化器也支持 `-s`。
  不指定种子时仍有意保留随机性；固定种子不证明跨平台字节一致。
- 旧 highlevel parser 退出码问题已有修正，不能把“两个 parser 出错都返回 0”
  套用到此版本。
- [Issue #1](https://gitlab.com/malbolge20/malbolge20_creator/-/work_items/1)
  记录内联递归 Fibonacci 误编译；拆分调用仅验证了该特定 workaround。
  [Issue #2](https://gitlab.com/malbolge20/malbolge20_creator/-/work_items/2)
  单独记录 ternary 语法/词法错误仍返回成功。报告限定版本，既不是所有程序的
  根因结论，也不证明最新 main 的状态。

**2026-11-10 核对 issue 状态：**#1/#2 均为 Open，未见公开回复。已读取两条
issue 页面，但没有重新验证最新 main。issue 未关闭不等于没有后续修复。

以下旧版说明为历史夹具与移植一致性而保留，对应 highlevel `5c4fb169`、ternary
`bf6b493b`、lowass `34b743f5`；独立解释器版本另在下方固定。
不要静默用新上游产物替换这些夹具，也不要将其计时当成对整合工具链的比较。

## 1. 获取

完整测试套件的独立 C 正确性门禁只需下面的显式准备命令，无需克隆整个工具链：

```bash
uv run --no-sync python scripts/verify_mb_reference.py fetch
```

它仅获取固定上游版本 `21ebda787362ab009276e216be34c169e4d049f4` 的
`malbolge20.c` 及 MIT 声明，校验两份文件哈希并保留 TLS 证书验证。
已有内容不同的本地文件会被拒绝而非覆盖。CI 还在受保护的编译器 PATH 中
确认 clang 存在，再运行独立门禁测试。
仪器化门禁与未经修改的参考程序均按 C99 编译，并定义
`_POSIX_C_SOURCE=200809L`，让 glibc 提供 `getopt`/`optind` 声明，无需修改固定源码。

以下**旧版**完整工具链获取方式仅用于历史编译对照和研究，不是当前上游的推荐
入口。各仓库许可证不同；旧 `highlevel-examples` 没有许可证文件。
浅克隆跟随服务端 tip，冻结对照前须检查/记录提交，并获取上方对应版本。

```bash
# 历史分仓，保留正常 TLS 验证
for r in highlevel highlevel-examples ternary lowass malbolge20-interpreter; do
  git clone --depth 1 \
    "https://git.trs.css.i.nagoya-u.ac.jp/malbolge/$r" "ref/nagoya-$r"
done

# LMAO(GPL-3,HeLL → 原版 Malbolge)
git clone https://github.com/esoteric-programmer/LMAO ref/LMAO
```

历史上游证书链故障应在遇到时具体诊断；当前正确性门禁准备使用经过验证的
HTTPS 和固定内容哈希。

## 2. 旧版构建（历史 macOS 实测）

| 工具 | 命令 | 坑 |
|---|---|---|
| LMAO | `cd ref/LMAO && PATH="/opt/homebrew/opt/bison/bin:$PATH" make` | 系统 bison 2.3 太旧(不支持 `%define parse.lac`),需 `brew install bison`(3.8,keg-only 不进 PATH) |
| nagoya-ternary | 同上加 PATH make | 同 bison 问题;大量 POSIX Yacc 警告可忽略 |
| nagoya-highlevel | 同上加 PATH make | 同上 |
| nagoya-lowass | `cd ref/nagoya-lowass/init && make` | 无;perl 阶段免构建 |
| nagoya-malbolge20-interpreter | `make -C ref/nagoya-malbolge20-interpreter` | Makefile 里 `-L/usr/local/opt/llvm/lib` 路径不存在仅告警 |
| ref/mbi.c(原版参考解释器,仓库自带) | `gcc -O2 ref/mbi.c -o ref/mbi` | 需删除 glibc 专有的 `#include <malloc.h>`(已修,已提交) |

通用平台坑:
- macOS 无 `timeout` 命令——脚本里用 Python `subprocess.run(..., timeout=)` 包装。
- LMAO 官方 README 写 `parse_mc.pl`,lowass 实际文件是 `parse_mc2.pl`。

## 3. 旧版管线与当前 Python 入口

```bash
# .mg → .mb，经旧 ref/ 包装脚本（风格/seed 与检错见下）
scripts/mg2mb.sh -s 1 prog.mg prog.mb

# 旧 C 子集 → .mg（旧 highlevel 出错可能仍 exit 0，检查 stderr）
ref/nagoya-highlevel/parser prog.c > prog.mg 2>err.txt; [ -s err.txt ] && echo FAILED

# Python 子集 → .mb（纯 Python 编译器，不调用外部 parser）
uv run python -m malbolge compile prog.py -o prog.mb

# 运行与交叉验证
uv run python -m malbolge --variant=malbolge20 prog.mb --engine python
ref/nagoya-malbolge20-interpreter/malbolge20 prog.mb   # 独立 C 参考

# HeLL → 原版 Malbolge(LMAO)
ref/LMAO/lmao program.hell -o program.mal
uv run python -m malbolge program.mal
```

**适用范围说明**:`python3 -m malbolge compile` 只接受 `.py` 源文件作为
输入。若场景是"手写的 `.mg` → `.mb`"(即已手写好 `.mg` 中间代码,不是从
`.py` 编译而来),`scripts/mg2mb.sh`(包装外部 ref/ 工具链)目前仍是唯一
的命令行(CLI)路径。想用纯 Python 完成这一场景,需在代码里直接调用
`translate_mg_to_mc()`(`malbolge/compiler/mg2mc.py`)与
`assemble_mc_to_mb()`(`malbolge/compiler/mc2mb.py`),而不经过 CLI。

## 4. 旧版确定性与错误处理

下列观察只适用于冻结的分仓版本，不适用于 §0 已支持固定种子的整合工具链：

- `ternary`:不给 `-s` 会随机化代码风格;固定 `-m -c -s 1`(mg2mb.sh 默认)。
- `parse_mc2.pl`:Perl 哈希序随机化 → `PERL_HASH_SEED=0`(mg2mb.sh 已做);会在 cwd 落 `info` 副产物(mg2mb.sh 已隔离到临时目录)。
- `lowass init`:对 padding 单元逐格 `srand(time(NULL))`,.mb **不可字节复现**(不影响行为)。字节稳定的夹具 = 生成一次后入库。
- `ternary`/`highlevel` 两个 parser **错误时退出码均为 0**,只能靠 stderr 判错。

`scripts/mg2mb.sh` 已将 ternary 非空 stderr 或空输出判为失败，并非无防护地
直接传递。它的 `-s` 固定旧 ternary 的风格选择，不固定旧初始化器的随机填充。

## 5. 验证惯例

- 对比项目与独立 C 解释器的精确程序输出，并核对源程序预期结果。两个 VM 一致
  运行错误编译的映像仍不合格；适用时还要断言输入消耗、错误和终止。
- 中间产物字节一致是受控参考移植回归检查；优化 lowering 可改变映像字节与步数，
  同时保持行为。
- 批量验证用 C 参考(快),pyMalbolge 抽样交叉。
- 运行时库自检:`uv run --no-sync python runtime/mg/tests/run.py`(19 项;`--py` 同时跑 pyMalbolge)。
- 全量测试：`uv run --no-sync pytest test/`。须先运行上方固定参考 fetch 并准备
  clang，独立门禁依赖它们。部分可选外部工具测试可能跳过，但不代表完整套件
  无需参考准备；慢测试/IR 范围见 `AGENTS.md`。
