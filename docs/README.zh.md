# docs 索引

> [English](README.md) | **中文**

本目录每份文档都有中英两版:`<name>.md`(英文)与 `<name>.zh.md`(中文),
内容保持同步;逆向工程类笔记以中文版为原稿。

## 编译器栈

| 文档 | 内容 |
|---|---|
| [highlevel-to-malbolge.zh.md](highlevel-to-malbolge.zh.md) | 路线决策:高级语言→Malbolge 可行性、推荐管线、里程碑、Python 前端 v1 与直连后端 |
| [python-subset-spec.zh.md](python-subset-spec.zh.md) | **规范性规格**:接受的 Python 子集 v1——按 AST 节点的接受白名单、与 CPython 的分歧(D1–D17)、诊断契约、审计附录 |
| [py2mg-backend.zh.md](py2mg-backend.zh.md) | `py → .mg` 直连后端(`--backend=direct`)设计:栈帧策略、递归环检测、与 C 路径的体积对比 |
| [perf-baseline.zh.md](perf-baseline.zh.md) | 性能剖析基线:两个热点、根因、修复前后测量、超线性拟合 |

## 语言规格(逆向工程)

| 文档 | 内容 |
|---|---|
| [mg-spec.zh.md](mg-spec.zh.md) | `.mg` 伪指令语言规格(逆向自 `ternary`,含实验验证) |
| [hell-spec.zh.md](hell-spec.zh.md) | HeLL 语言规格(逆向自 LMAO v0.6.0) |
| [lmao-internals.zh.md](lmao-internals.zh.md) | LMAO 汇编器内部算法分析(布局、自举生成) |
| [hell-assembler-design.zh.md](hell-assembler-design.zh.md) | Python 版 HeLL 汇编器设计(已搁置的备选路线;§6 讨论 GPL 问题) |

## 调研与背景

| 文档 | 内容 |
|---|---|
| [findings.zh.md](findings.zh.md) | **研究发现与贡献清单**(论文素材,持续更新):上游发现、本项目贡献、定量数据、理论推导、bug 复现、改进 backlog、许可 |
| [malbolge-landscape.zh.md](malbolge-landscape.zh.md) | 生态全景:历史脉络、工具谱系(生成器/HeLL-LMAO/名古屋)、名古屋论文全列表、调研方法 |
| [iwagane-arrays.zh.md](iwagane-arrays.zh.md) | 名古屋 2018 年未公开数组实现的解剖:`IND_OPR` 前端语法糖、步长为 2 的约束、`LOADI`/`STOREI` 设计建议 |
| [toolchain-guide.zh.md](toolchain-guide.zh.md) | 外部参考工具链的构建与复现指南(平台坑、确定性、验证惯例) |

运行时库文档见 [`runtime/mg/README.md`](../runtime/mg/README.md);
测试夹具出处见 `test/fixtures/hell/README.md` 与 `test/fixtures/nagoya/README.md`。
