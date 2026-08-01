# 工具链构建与复现指南

> [English](toolchain-guide.md) | **中文**

> **注(P4 之后)**:编译 Python/C/.mg 程序已**不需要**本文档的任何
> 外部工具——`malbolge/compiler/` 的纯 Python 移植覆盖了全链
> (`python3 -m malbolge compile prog.py -o prog.mb`)。本文档保留给
> **conformance 对拍**(与参考实现比对)与上游考古场景。
>
> 外部参考工具的获取、构建与使用,含全部已踩过的平台坑
>(macOS/Darwin 实测)。工具本体均在 gitignore 的 `ref/` 下,不入库。

## 1. 获取

```bash
# 名古屋五仓库(MIT;站点证书链不完整,需跳过验证)
for r in highlevel highlevel-examples ternary lowass malbolge20-interpreter; do
  GIT_SSL_NO_VERIFY=1 git clone --depth 1 \
    "https://git.trs.css.i.nagoya-u.ac.jp/malbolge/$r" "ref/nagoya-$r"
done

# LMAO(GPL-3,HeLL → 原版 Malbolge)
git clone https://github.com/esoteric-programmer/LMAO ref/LMAO
```

网页资料同理:`curl -sk https://www.trs.css.i.nagoya-u.ac.jp/projects/Malbolge/`。

## 2. 构建(macOS 实测)

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

## 3. 管线用法

```bash
# .mg → .mb(推荐入口;固定 seed 与风格,检错见下)
scripts/mg2mb.sh -s 1 prog.mg prog.mb

# C 子集 → .mg(highlevel;注意它出错也退出 0,必须检查 stderr)
ref/nagoya-highlevel/parser prog.c > prog.mg 2>err.txt; [ -s err.txt ] && echo FAILED

# Python 子集 → .mb(本项目前端,内部处理上述检错)
python3 -m malbolge compile prog.py -o prog.mb

# 运行与交叉验证
python3 -m malbolge --variant=malbolge20 prog.mb
ref/nagoya-malbolge20-interpreter/malbolge20 prog.mb   # C 参考,快 15-100x

# HeLL → 原版 Malbolge(LMAO)
ref/LMAO/lmao program.hell -o program.mal
python3 -m malbolge program.mal
```

## 4. 确定性与可复现

- `ternary`:不给 `-s` 会随机化代码风格;固定 `-m -c -s 1`(mg2mb.sh 默认)。
- `parse_mc2.pl`:Perl 哈希序随机化 → `PERL_HASH_SEED=0`(mg2mb.sh 已做);会在 cwd 落 `info` 副产物(mg2mb.sh 已隔离到临时目录)。
- `lowass init`:对 padding 单元逐格 `srand(time(NULL))`,.mb **不可字节复现**(不影响行为)。字节稳定的夹具 = 生成一次后入库。
- `ternary`/`highlevel` 两个 parser **错误时退出码均为 0**,只能靠 stderr 判错。

## 5. 验证惯例

- 双解释器逐字节对拍(pyMalbolge vs 参考 C 解释器)是所有 fixture 的准入标准。
- 批量验证用 C 参考(快),pyMalbolge 抽样交叉。
- 运行时库自检:`python3 runtime/mg/tests/run.py`(19 项;`--py` 同时跑 pyMalbolge)。
- 全量测试:`python3 -m unittest discover test/`(不依赖 ref/ 工具,fixtures 已入库;e2e 测试在工具缺失时自动 skip)。
