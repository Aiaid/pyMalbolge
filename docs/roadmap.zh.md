# 公开候选路线图

> [English](roadmap.md) | [中文](roadmap.zh.md)

2026-11-13。本候选分支仅包含可靠性/文档与手写 MG CLI；源码改动不代表已经发布。

| 状态 | 范围 | 下一道验收 |
|---|---|---|
| 候选 | 纯 Python `compile-mg`、UTF-8、别名检查、单文件原子输出 | [用户指南](user-guide.zh.md)；限定范围回执 |
| 候选 | Web 构建/暂存测试、Windows 路径/字节/权限修复、native CI | 运行远程 CI 与真实浏览器检查；本地测试不代表这些验收通过 |
| 独立研究分支 | 新 JIT profiling、MLIR 算术导出器、覆盖写入消除 pass | 继续独立正确性与性能审查；本候选分支不包含这些实现 |
| 既有基线 | Native VM 与受保护的实验性 ARM64 NOP JIT | Windows native 可用不代表 Windows JIT 可用 |
| 待实现 | 直接 semantic-to-LAL、完整变量 SSA、运行时数组/字符串、Unshackled | 先定义有界语义与独立执行验收 |

已有发布声明仍以 [1.2.0 回执](notes/pypi-1.2.0-publication.json)的范围为准。
本公开摘要不披露私有研究文档。
