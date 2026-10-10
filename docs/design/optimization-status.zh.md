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

### 开启方式核对（2026-10-10）

编译器默认是 `backend=c`、`ir_frontend=compat`、`target_pipeline=text`，
风格为 `cluster/main`。体积/运行表显式比较不同路径；其中 direct 或 semantic
的成绩，不是普通 compile 命令的默认结果。

| 工作 | 开启方式 |
|---|---|
| C/direct 算术捷径、临时量/帧处理、MC 布局/编码缓存、启动代码存储/发射及共享 Python VM 原语 | 在适用实现中自动生效，无需额外优化开关。 |
| direct Python→MG 前端 | 选择 `--backend=direct`，内部已验收优化自动生效。 |
| semantic IR 和已验收具名优化 profile | 选择 `--backend=ir --ir-frontend=semantic` 并安装 `ir` extra。进入 semantic 后，已验收 profile 本身就是默认；`--opt-level=1` 显式声明该选择，`0` 则仅校验。单独 `--backend=ir` 仍是 compat 前端。 |
| 原生结构化 LAL/image 传递 | 选择 `--target-pipeline=structured`，默认仍为 `text`。属于接口实验，direct 前端产物缩小来自其自身 lowering。 |
| 编译缓存 | 传入 `--cache-dir`；默认关闭，冷编译测量不使用缓存。 |
| 十进制输出候选及被拒绝的批量 NOP 实验 | 排除已验收默认策略；十进制候选需手动选择 pass。 |
| 目标 AST 初始化/循环/谓词原型 | 当前未提交 semantic adapter 内，三个接口选项在选中该路径后默认开启。冻结工作 benchmark 包含它，但其源码状态及具名 semantic profile 分别标明。 |
| 原生 VM / JIT | 已提交代码基线 `1a7b88b` 的 `run20` 默认 Python，native/JIT 通过库的 engine 显式选择。当前工作目录另有另一会话未提交的 `auto` 批处理原生优先策略，JIT 仍显式选择；原生安装/构建变化也属独立工作。 |

已提交 direct 路径的选择：

```bash
uv run python -m malbolge compile program.py --backend=direct -o program.mb
```

显式 semantic 和 structured 选择：

```bash
uv sync --extra dev --extra ir
uv run --no-sync python -m malbolge compile program.py --backend=ir \
  --ir-frontend=semantic --opt-level=1 --target-pipeline=structured -o program.mb
```

统一产物对照直接调用固定原版 C 二进制，产品的默认引擎变化不影响该测量 cohort。

| 层 | 已实现工作 | 状态与作用 |
|---|---|---|
| Python→MG 前端 | direct lowering、函数内临时量复用、递归调用图、递归帧及跨调用活跃临时量保护 | 已集成；省去 C 表示和不必要的非递归自身帧保护。调用递归 callee 仍可能保存返回地址/scratch。 |
| C/direct 算术 | 常量折叠、除一/模一消除、小字面量乘法加链、按需算术/十进制 helper | 默认已集成；适用时减少目标操作，保持求值、副作用、错误及 20-trit 环语义。 |
| 语义 IR | 七类具名算术/数据流/控制/表达式变换、可校验 pass 边界、源码位置与独立语义执行器 | 显式选择 semantic 前端后的默认验收 profile；原始前端 API 与等级 0 仍只生成/校验。 |
| MG→LAL | 四种既有确定性风格、无额外依赖的原生结构化生成器 | 风格显式选择；原生目标管线为 opt-in 接口试验，尚无按调用点自动成本选择。 |
| LAL→MB | 按版本失效的移动搜索缓存、指令编码表、first-fit 占用/键缓存、紧凑页面源码、流式输出及类型化映像传递 | 宿主/存储优化已集成；部分保持产物字节，改善编译开销。原生传递仍 opt-in。 |
| VM/调试器 | 紧凑不可变源码、周期默认值、类型化 COW 内存、分组 trit crazy 查表、有预算字节 I/O/执行和有界历史 | 运行时/存储工作已集成；解释器吞吐与目标指令数量分别衡量。 |
| CLI/工具 | 原子输出、路径别名检查、完整性校验内容缓存、阶段指标、固定负载基准与源码审计 | 已集成；热缓存行为与冷编译性能分开。 |

编译器仍默认 C 前端，IR 默认 compat，目标管线默认 text。语义 pass 和
原生低层传递是独立选择。xDSL 继续惰性导入，基础 C/direct 保持 Python 3.8。

## 证据与边界

- [Python QoS 验收](../notes/python-qos-validation.json)：语言/运行时契约、
  紧凑存储、实际目标执行、缓存与打包。
- [语义 pass 验收](../notes/semantic-pass-validation.json)：已验收源变换及
  重复的编译/体积/运行对照。
- [结构化传递验收](../notes/structured-lowering-validation.json)：原生接口、
  库/CLI/IR 接入及排除其他本地原型的 HEAD 加本轮代码回归。
- [目标接口原型验收](../notes/target-interface-validation.json)：已记录本地
  实验，本轮没有集成其实现。

性能结论按负载与测量 cohort 限定。算术恒等式、表达式折叠和传播可以
同时改善三种成本；编码/装箱缓存主要改善宿主编译；VM 查表主要改善执行
吞吐。原生传递建立共同后端接口，尚未证明普遍提速。既有风格选择可以
独立改变体积与执行步数。

## 实验与待办

紧凑十进制输出因目标成本回退，仍排除默认语义 profile；批量 NOP 发射
因宿主耗时回退被拒绝。省略生成局部入口初始化、结构化目标循环和原生
while 谓词仍是另一会话的未提交原型；其消融收益不能证明已追上旧 direct。
完整变量 SSA/活性、动态乘法重设计、按调用点成本选择、分派/flag 最小化
及新布局/启动策略仍待实现。

最新独立正确性门禁已验证固定程序库的输出和终止，包括旧 C/direct 超时
映像。2026-10-09 Python cohort 中 23 个不完整样本的完整耗时仍不可得；
独立统一 C VM cohort 仅 C/semantic 的 `12!` 超时，direct 完成全部 32 个
固定程序库输入。历史及定向测试
数量不相加成当前完整测试总数。

后续生成优化允许 MB 字节和步数减少，验收依据为可观察语义、必要机器
不变量及完整编译时间/体积/运行成本。字节一致用于接口回归，不作为优化目标。
