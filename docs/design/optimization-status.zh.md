# 优化与成果现状

> [English](optimization-status.md) | **中文**
>
> 快照：2026-10-09。区分已验收代码、显式实验和已记录的本地原型。
> 带日期的完整测量保存在私有配套仓库的优化总览；公开验收记录见下方。

> 2026-10-10 后续：最新冻结工作 cohort（含本地目标接口原型）在计时前
> 通过全部 123 个独立真实映像契约。36 次冷编译及 96 个运行组合全部尝试，
> 73 个 Python 样本正常完成，23 个触及整子进程期限；最终源码/映像/状态
> 复核通过。[验收摘要](../notes/latest-corpus-validation.json)明确工作 cohort
> 和单轮边界，此次不提升原型状态，也不证明普遍提速。

> 2026-10-10 同 VM 后续：重建相同冻结已验收 MB，用同一固定、未改写原版
> C-O3 二进制运行，包含真实原版 GCD。99 个身份全部尝试：97 正常完成、
> 2 整子进程超时、无输出失败；源码/映像/VM/清理复核通过。direct GCD 为
> 276.78 MB，原版为 597.97 MB；本轮整子进程墙钟为 9.11 秒和 18.83 秒。
> [统一 VM 验收](../notes/common-vm-validation.json)将产物比较与解释器/
> 默认引擎工作分开。

## 已实现的各层

### 开启方式核对（2026-10-10，当前分支）

当前集成默认采用 `backend=auto`、O3、`target_pipeline=structured` 和
`cluster/main`。direct 与适用的已验收 semantic 候选按预测最终 MB 精确
字节数竞争，生成启动代码之前即完成选择，相等时选 direct。完整规则见
[编译策略](compiler-optimization.zh.md)，最终组合验收见
[集成记录](../notes/compiler-optimization-validation.json)。

本次集成之前的开启方式核对记录了 C/compat/text 默认值和显式编译缓存。
上方带日期的性能表仍对应显式选择的冻结路径，并非新的 auto 选择性能测量。

| 工作 | 开启方式 |
|---|---|
| direct Python→MG 前端与算术捷径 | direct 是 auto 必备候选；O1–O3 启用算术捷径，O0 关闭。`--backend=direct` 锁定前端。 |
| semantic IR 与已验收具名 profile | 受支持 IR 环境可用时作为 O3 候选；显式 IR 默认 semantic。O0 仅校验，优化等级使用已验收 profile；`--ir-frontend=compat` 选择原兼容桥。 |
| 原生结构化 LAL/image 传递 | O2/O3 默认，`--target-pipeline=text` 显式退出。单纯传递方式不能解释 direct 产物缩小。 |
| 编译缓存 | O3 CLI 自动使用源码旁缓存，单产物门槛 64 MiB；`--no-cache` 关闭，`--cache-dir` 显式选择缓存。库编译没有持久缓存。 |
| C 参考算术、帧处理、MC 布局/编码缓存、启动代码存储/发射及共享 Python VM 原语 | 保留在各自适用实现内。C0 仍保留参考算术固有行为，不是完全无算术优化的基线。 |
| 目标 AST 初始化/循环/谓词接口 | 已集成并通过本地验收；semantic O1–O3 开启三个开关，O0 关闭。最终组合验收独立于旧原型记录。 |
| 十进制输出候选及被拒绝的批量 NOP 实验 | 排除已验收默认策略；十进制候选需手动选择 pass。 |
| 原生 VM / JIT | 运行引擎与打包工作独立管理和验收。编译器 O3 不开启 JIT，JIT 仍显式选择。 |

默认选择与显式 direct 选择：

```bash
uv run python -m malbolge compile program.py -o program.mb --stats
uv run python -m malbolge compile program.py --backend=direct -o direct.mb
```

显式 semantic 选择：

```bash
uv sync --extra dev --extra ir
uv run --no-sync python -m malbolge compile program.py --backend=ir \
  --ir-frontend=semantic --opt-level=1 --target-pipeline=structured -o semantic.mb
```

统一产物对照直接调用固定原版 C 二进制，产品的默认引擎变化不影响该测量 cohort。

| 层 | 已实现工作 | 状态与作用 |
|---|---|---|
| Python→MG 前端 | direct lowering、函数内临时量复用、递归调用图、递归帧及跨调用活跃临时量保护 | 已集成；省去 C 表示和不必要的非递归自身帧保护。调用递归 callee 仍可能保存返回地址/scratch。 |
| C/direct 算术 | 常量折叠、除一/模一消除、小字面量乘法加链、按需算术/十进制 helper | 默认已集成；适用时减少目标操作，保持求值、副作用、错误及 20-trit 环语义。 |
| 语义 IR | 七类具名算术/数据流/控制/表达式变换、可校验 pass 边界、源码位置与独立语义执行器 | 适用的 O3 semantic 候选或显式 semantic 前端使用已验收 profile；原始前端 API 与 semantic O0 仍只生成/校验。 |
| MG→LAL | 四种既有确定性风格、无额外依赖的原生结构化生成器 | 风格仍显式选择，原生目标传递为 O2/O3 默认；auto 比较前端，不进行按调用点风格选择。 |
| LAL→MB | 按版本失效的移动搜索缓存、指令编码表、first-fit 占用/键缓存、紧凑页面源码、流式输出及类型化映像传递 | 宿主/存储优化已集成；部分保持产物字节，改善编译开销。原生传递为 O2/O3 默认。 |
| VM/调试器 | 紧凑不可变源码、周期默认值、类型化 COW 内存、分组 trit crazy 查表、有预算字节 I/O/执行和有界历史 | 运行时/存储工作已集成；解释器吞吐与目标指令数量分别衡量。 |
| CLI/工具 | 原子输出、路径别名检查、完整性校验内容缓存、阶段指标、固定负载基准与源码审计 | 已集成；热缓存行为与冷编译性能分开。 |

新默认策略组合了候选选择与结构化传递，同时保留各自显式开关。xDSL
继续惰性导入，无额外依赖的 direct 候选和显式 C/direct 保持 Python 3.8。
尺寸选择不证明编译时间或运行时间在所有场景都最优。

## 证据与边界

- [Python QoS 验收](../notes/python-qos-validation.json)：语言/运行时契约、
  紧凑存储、实际目标执行、缓存与打包。
- [语义 pass 验收](../notes/semantic-pass-validation.json)：已验收源变换及
  重复的编译/体积/运行对照。
- [结构化传递验收](../notes/structured-lowering-validation.json)：原生接口、
  库/CLI/IR 接入及排除其他本地原型的 HEAD 加本轮代码回归。
- [目标接口原型验收](../notes/target-interface-validation.json)：较早的本地
  实验记录，后续实现已集成并通过本地验收。
- [编译策略集成验收](../notes/compiler-optimization-validation.json)：新默认
  策略与目标接口的最终组合验收记录。

性能结论按负载与测量 cohort 限定。算术恒等式、表达式折叠和传播可以
同时改善三种成本；编码/装箱缓存主要改善宿主编译；VM 查表主要改善执行
吞吐。原生传递建立共同后端接口，尚未证明普遍提速。既有风格选择可以
独立改变体积与执行步数。

## 实验与待办

紧凑十进制输出因目标成本回退，仍排除默认语义 profile；批量 NOP 发射
因宿主耗时回退被拒绝。省略生成局部入口初始化、结构化目标循环和原生
while 谓词已集成并通过本地验收；原消融收益不能证明性能已追上 direct。
完整变量 SSA/活性、动态乘法重设计、按调用点成本选择、分派/flag 最小化
及新布局/启动策略仍待实现。

最新独立正确性门禁已验证固定程序库的输出和终止，包括旧 C/direct 超时
映像。2026-10-09 Python cohort 中 23 个不完整样本的完整耗时仍不可得；
独立统一 C VM cohort 仅 C/semantic 的 `12!` 超时，direct 完成全部 32 个
固定程序库输入。历史及定向测试
数量不相加成当前完整测试总数。

后续生成优化允许 MB 字节和步数减少，验收依据为可观察语义、必要机器
不变量及完整编译时间/体积/运行成本。字节一致用于接口回归，不作为优化目标。
