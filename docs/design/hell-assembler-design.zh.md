# Python 版 HeLL 汇编器设计文档

> [English](hell-assembler-design.md) | **中文**

> 目标:在 pyMalbolge 中实现 HeLL → Malbolge 汇编器,行为兼容 LMAO v0.6.0。
> 依据:`docs/specs/hell-spec.zh.md`(语言规格)与 `docs/upstream/lmao-internals.zh.md`(LMAO 算法分析)。
> 状态:已搁置——等待许可证决策(见 §6)。2026-07-20 起草。

## 1. 目标与范围

- **做**:完整的 HeLL 前端(词法/语法/语义)+ LMAO 兼容的布局与自举代码生成,
  输出可被 pyMalbolge / 参考解释器执行的原版 Malbolge(10 trits)程序。
- **验收标准**:`test/fixtures/hell/` 六个 .hell 示例,用本汇编器产出的 .mal
  必须通过 `test/test_hell_examples.py` 的全部 I/O 用例(与 LMAO 参考产物同行为)。
- **暂不做**(留扩展口):Malbolge20 目标(布局与生成器需按 `MalbolgeConfig`
  参数化,但数据模块的魔法常量是 10-trit 专属,20-trit 需重新推导);
  HeLL 之上的高级语言前端(下一阶段)。

## 2. 包结构

```
malbolge/hell/
├── __init__.py      # assemble(source: str, *, fast=False) -> str 顶层 API
├── lexer.py         # 上下文相关 tokenizer
├── hast.py          # AST 数据模型(避免与内置 ast 混淆)
├── parser.py        # 递归下降解析器 → AST
├── labels.py        # 标签表、R_/U_ 前缀解析、虚拟 RNop 合成
├── xlat.py          # XLAT2 表、immutable_nops、循环存在性、possible_positions
├── exprs.py         # .DATA 表达式求值(mod 59049 算术、旋转、crazy)
├── layout.py        # 三分区布局、put_all_memcells_together、RQ 定位
├── geninit.py       # 自举代码生成器(State 模拟、常量合成、set_dreg)
├── datamodule.py    # init_datamodule 字面前缀 + 魔法常量(源自 LMAO,见 §6)
├── output.py        # denormalize、折行、don't-care 填充
└── errors.py        # HellSyntaxError / HellSemanticError / LayoutError(带行号)
```

CLI 挂进现有入口:`python -m malbolge asm program.hell -o program.mal`
(`__main__.py` 新增 `asm` 子命令,与 `run`/`debug` 并列)。

## 3. 数据模型(hast.py)

对照 LMAO 的 struct,Python 化:

| LMAO | Python | 说明 |
|---|---|---|
| XlatCycle 链表 | `XlatCycle(ops: tuple[int,...], rnop: bool)` | 不可变;`rnop=True` 即自环 Nop |
| DataAtom | `LabelRef(name, kind)`,kind ∈ {PLAIN, R, U};U 带 `anchor` | |
| DataCell 树 | `Expr` 递归节点(Const / LabelRef / BinOp / DontCare / NotUsed) | 求值在 exprs.py |
| Code/DataBlock 双向链表 | `Block(kind, offset, cells: list[Cell], labels: dict[str,int])` | cells 下标即块内偏移 |
| LabelTree(BST) | `dict[str, tuple[Block,int]]` | |
| MemoryCell[59049] ×4 | `Layout` 类:`usage: bytearray(59049)` + `cells: dict[int, Cell]` | usage 枚举同 LMAO 六态 |
| State/Module/Cell | `GenState`(dataclass):A、D(module,pos)、模块格值镜像 | geninit.py |

## 4. 流水线

```
source ──lexer──> tokens ──parser──> AST(blocks, labels)
  ──labels──> 前缀解析 + 虚拟 RNop 合成
  ──xlat──> 每个代码块的 possible_positions[94] + needs_initialization
  ──路由──> fixed(.OFFSET) / preinitial(可嵌入) / toinitial(运行时构造)
  ──layout──> 三分区合并 + RQ 定位(尺寸估计循环)
  ──exprs──> 数据格求值(标签地址已定)
  ──geninit──> 归一化自举代码(State 模拟)
  ──output──> denormalize + 前缀/RQ/填充 → .mal 文本
```

与 LMAO 一致的两个全局循环:
- **尺寸估计循环**:自举代码长度影响 RQ 位置,RQ 位置影响布局,布局影响自举代码长度。
  沿用 LMAO 的"估计→失败→增量重试"(初值取 LMAO 同款启发式,增量 32;
  后续可优化为二分,但 M4 前先保持与 LMAO 同步以便对拍)。
- **fast 模式**:直接用满内存,失败回退普通模式(对应 `-f`)。

## 5. 里程碑与验证

每个里程碑都有独立的对拍手段,不做"最后一把梭"式集成:

| 里程碑 | 内容 | 验证 |
|---|---|---|
| **M1 前端** | lexer + parser + AST | 六个 fixture 解析成功;块数/格数/标签集与 LMAO `-d` 调试输出对照;错误用例单测(spec §3.5 全清单) |
| **M2 语义层** | 前缀解析、xlat 存在性、表达式求值 | xlat:对全部 94 残基 × 常见循环枚举断言与 C 版一致(可写一次性 C 驱动导出金标准表);表达式:手算用例 + 边界(mod、负数回绕、旋转越界警告) |
| **M3 布局** | 三分区、合并、RQ | 与 LMAO `-d` 输出的标签地址/分区边界逐项 diff |
| **M4 自举生成器** | datamodule、State、常量合成、单格驱动 | **字节级对拍**:同一 .hell,我们的 .mal 与 LMAO 的 .mal 逐字节 diff(算法照抄 + 贪心顺序一致时应当全同,任何 diff 都是 bug 信号) |
| **M5 集成** | 输出、CLI、端到端 | `test_hell_examples.py` 参数化跑"本汇编器产物";六示例 I/O 全过 |
| **M6(后续)** | Malbolge20 参数化 | 需先为 20-trit 重新推导数据模块,单独立项 |

**验证总原则**:M4 以字节级一致为目标(最强正确性证明,diff 即验证);
若某处 LMAO 行为依赖 C 未定义行为无法复刻,降级为行为一致(I/O 对拍)并记录偏差。

## 6. 关键设计决策

1. **字节级兼容优先**(M4):照抄算法与贪心顺序,产物应与 LMAO 逐字节相同。
   这把"汇编器对不对"简化成 `diff`,调试成本大幅降低。达成后,后续优化
   (更好的布局、更短的初始化)在字节级基线之上做,用行为对拍守护。
2. **许可(待项目所有者确认)**:`datamodule.py` 的 init_datamodule 前缀
   字符串与魔法常量必须从 LMAO(GPL-3.0)逐字节复制,布局/生成器算法也是
   逐行复刻——`malbolge/hell/` 子包实质上是 LMAO 的衍生作品。选项:
   a) 子包单独标注 GPL-3.0(仓库变混合许可,需在 README 说明);
   b) 整个项目转 GPL-3.0;
   c) 重新推导数据模块与初始化策略(工作量大,失去字节对拍能力)。
   **建议 a**;实现开始前需确认。
3. **诊断比 LMAO 严格**:除零 → 显式报错(LMAO 是 UB);标签指向 `?-` →
   报错(LMAO 仅警告 + 可能崩溃);全部错误带行号。宽松处保持兼容:
   旋转量 ≥10 取模 + 警告(与 LMAO 同)。
4. **10-trit 常量不复用 core.py 的参数化版本**:geninit 内部大量 10-trit
   专属魔法值,直接用本包常量(POW10 等),避免误伪装成"已参数化"。
   真正的参数化留给 M6。
5. **性能**:59049 格规模,纯 Python 足够;不做过早优化。

## 7. 风险

| 风险 | 缓解 |
|---|---|
| gen_init 状态模拟与 C 版有细微偏差(难度榜第 1) | M4 字节对拍 + 按 fixture 从小到大(simple_hello → adder 55KB)逐个攻克;必要时给 LMAO 加打印补丁导出中间 State 轨迹对拍 |
| 布局 off-by-one(难度榜第 2) | M3 用 `-d` 调试文件对拍标签地址 |
| C 未定义行为(`%= C2` 边界、除零)被示例意外依赖 | 先复刻 C 的实际行为,偏差点集中在 exprs.py 一处并注释 |
| 尺寸估计循环不收敛/慢 | 与 LMAO 同参数起步;仅在测试全绿后再调 |
