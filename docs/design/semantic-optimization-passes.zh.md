# 显式语义优化 passes

> [English](semantic-optimization-passes.md) | **中文**
>
> 状态：算术/数据流/控制及有界表达式发射已验收为语义默认 profile。
> 十进制输出因目标体积/运行回退保留为显式实验。架构基线为 aabe099。

## Pass 契约

| 名称 | 变换 | 必须保持 |
|---|---|---|
| fold-arithmetic | 字环常量算术、一元及已确定比较 | 不折掉零除错误；只内联实际到达的比较生产者 |
| simplify-arithmetic | 算术恒等式、吸收元、除一/模一 | 操作数已求值，保留调用、读取及可能失败的计算 |
| lower-constant-multiply | 有界二进制/NAF/模环取负加法链 | 精确模 3**20，乘数值只求值一次；昂贵因子保留乘法 |
| simplify-control | 常量分支、确定的布尔前缀及 false 循环 | 保留有序已到达 regions；false 循环条件执行一次 |
| propagate-constants | 顺序代码及保守合流中的已证明槽位事实 | 初始未知、调用清全局事实、分析循环前杀掉所有可能写入 |
| eliminate-pure-computation | 不再使用且已证明不会失败的计算 | 保留存储/声明、未证明读取、调用、I/O、名称陷阱和可能失败的除法 |
| inline-pure-arithmetic | 紧邻加减链的显式目标表达式发射提示 | 仅由同块下一加减操作使用一次，深度有界；适配器独立复核提示 |
| lower-decimal-output | 常量文本或类型化非递归格式化调用 | 使用原 SSA 操作数，保持打印/输入/错误顺序、无符号格式和无碰撞 helper 复用 |

数据流工作有预算，部分改写也保持有效；乘法展开有明确操作预算。
存储与声明特意保留，本阶段不是完整变量 SSA 或全局死存储删除。
十进制格式化函数使用有界加减循环及单数字快速路径，不用通用乘除、取模
或递归。
表达式发射 pass 不改写源码求值，只在独立复核邻接与单次使用后减少目标 AST
捕获。每段最多内联 16 层，最终物化的消费者可多一层；伪造或过期标记不能
绕过证明。

每个 pass 通过既有校验 runner 执行，改写保留源码位置，默认克隆输入，
可查看前后计数/摘要。结构校验之外还需要独立语义测试；不自动启用上游
优化套件。

## 后端边界与比较方案

语义目标适配器关闭旧 direct 前端的算术折叠、除一/模一及小乘法快捷路径，
这些决策归显式语义 pass。C/direct 参考路径保留原默认；命名/语法检查、
静态控制处理、字面量输出、ABI/布局、汇编缓存和 VM 实现仍各自归属原层。
因此关闭比较是“算术优化关闭”，不是声称整个编译器完全没有优化。

比较方案：

- legacy_direct：原 direct 源码路径。
- semantic_legacy：只校验，启用旧目标算术，作为架构基线对照。
- semantic_none：只校验，关闭旧目标算术。
- semantic_passes：显式算术/数据流/控制候选序列。
- semantic_decimal：上述序列加十进制输出 lowering。

候选顺序定义在 semantic_passes.py，重复清理在报告中显式出现。
默认启用是行为与性能验收后的独立策略改变。指令编码/装箱缓存、VM crazy
查表属于实现优化，不伪装成 IR pass。

已验收顺序为 OPTIMIZATION_PASSES，现为语义路径默认。
用 --backend=ir --ir-frontend=semantic --opt-level 0 只做校验，
--opt-level 1 使用已验收 profile；显式 --semantic-passes 是等级的替代选择。
原始前端库 API 仍不优化；显式 compat 保留 direct 兼容桥。整程序 O3
auto 可选择已验收 semantic 候选，显式 IR 默认 semantic。C/direct 算术
开关遵循[现行策略](compiler-optimization.zh.md)。
lower-decimal-output 已注册，但不在等级 1 内。不声称普遍提速：中性负载
目标结构不变，校验/分析增加少量宿主开销。失败十进制候选保留为显式实验，
便于可复现调查。

## 可复现验收

scripts/benchmark_semantic_passes.py 提供固定源码/输入/输出/输入消费契约、
新子进程、轮换交错、每次冷编译复用多输入，以及 JSON/CSV 检查点。

```sh
uv run --no-sync python scripts/benchmark_semantic_passes.py \
  --cases char_io literal_fold constant_propagation \
  --variants semantic_legacy semantic_none semantic_passes \
  --repeats 3 --warmups 1 --output /private/tmp/new-semantic-pass-comparison
```

同时记录编译 wall/CPU、最终 MB 字节/哈希和目标运行 wall/CPU/步数，包含
硬件/负载及源码指纹。预热单独保存，不强制刷新 OS 缓存；用共同完整轮次
做配对比较。整个子进程超时没有 VM 计时/步数；步数预算停止保留诊断，
不混入完整运行样本。不能跨输入累加共用编译成本。

这些测量不归一化硬件或后台活动。正确性失败或代价不可接受的候选继续
保留为显式实验；新布局/调度协议及动态乘法 helper 重设计仍需要各自的
不变量/终止性调查。
