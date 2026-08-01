# 性能标定与剖析基线(2026-07-21)

> [English](perf-baseline.md) | **中文**

> 仅测量与剖析,不含优化实现。基准脚本与中间产物见
> `/Users/anend/.claude/jobs/1d5df563/tmp/perf/`(会话临时目录,未入库)。

## 0. 环境

- `python3 --version`: Python 3.14.6(`/opt/homebrew/opt/python@3.14/bin/python3.14`)
- CPU: `sysctl -n machdep.cpu.brand_string` → **Apple M1 Pro**
- `pypy3`: **未安装**(`which pypy3` / `which pypy` 均未找到)。Homebrew 有
  可用 formula(`brew search pypy` → `pypy3.10`、`pypy3.11`),安装命令:
  `brew install pypy3.11`。本次未执行安装(任务要求不自行装大包),PyPy
  对比**跳过**,加速比未知——见 §4 的间接判断。
- 每项基准跑 2 次取更优值(`best_of_2`)。

## 1. 解释器基准(malbolge20,子进程 `python3 -m malbolge --variant=malbolge20`)

| 用例 | .mb 体积 | 步数(参考值) | best_of_2 耗时 |
|---|---|---|---|
| hello20.mb | 188,207 B | 46,417 | 0.8885 s |
| mg_e_call.mb | 799,471 B | 未单独计数,量级更大 | 1.1992 s |

对照内部研究日志(private,非本仓库)§C 节记录的 hello20 "0.6 s":此次
子进程整体耗时 0.89 s,差值主要是 Python 3.14 解释器自身启动 + import
开销(子进程整体计时 vs. 该日志未注明测量方式),量级一致,无回归。

## 2. 解释器 cProfile 剖析(进程内调用 `malbolge20.eval()`,不含子进程/CLI 开销)

### hello20.mb(46,417 步)

```
1523770 function calls in 1.424 s
tottime  cumtime  函数
0.052    1.424    malbolge20.py:121 eval()  [主循环本体]
0.051    1.127    core.py:236 SparseMemory.__getitem__          (258,784 次)
1.050    1.050    core.py:80 crazy()                             (172,437 次)
0.029    1.048    core.py:171 _materialize_block()                (170 次)
0.000    0.312    core.py:201 _seed_for_block()
0.118    0.178    core.py:348 parse_source()
```

### mg_e_call.mb(更大用例)

```
5824673 function calls in 2.372 s
tottime  cumtime  函数
0.217    2.372    malbolge20.py:121 eval()
0.213    1.127    core.py:236 __getitem__                        (1,087,062 次)
0.016    0.797    core.py:171 _materialize_block()                 (732 次)
0.485    0.746    core.py:348 parse_source()
0.709    0.709    core.py:80 crazy()                             (112,596 次)
0.248    0.261    core.py:201 _seed_for_block()
```

**头号热点(反直觉的发现)**:两个用例中,主解释循环本体(`eval()` 的
`tottime`)占比都很小(hello20 仅 3.7%,mg_e_call 仅 9.1%)。真正吃掉
70–80% 运行时的是 **`SparseMemory` 的懒块物化**——`_materialize_block()`
每次被触发时,要用 `crazy()` 把整个 **59,049 格(3^10)的默认填充块**
从头算到尾(逐格调用 `crazy()`,20-trit 情形下每格还要跑一个 20 次的
内层 for 循环),即便这个 46K 步的小程序实际只会读其中极少数格子。
hello20 触发了约 3 个块的物化(172,437 ≈ 3 × 59,049 次 `crazy()` 调用),
mg_e_call 触发约 2 个块(732 次 `_materialize_block` 里绝大多数是缓存命中,
真正首次物化的块不多但每块代价固定)。`parse_source()` 在 mg_e_call 上也
不可忽视(0.746s cumtime,主要是 `ord()` 逐字符调用,799K 字符量级)。

**可优化性判断**:这不是"主循环慢",而是"整块预物化"这个缓存粒度选择
本身代价过高——块大小固定为 `3^(trit_width/2)`,与程序实际访问的稀疏
程度无关。已有 `_block_seed_jump_map`(§A5,用于跨块跳种子)证明了
crazy 填充可以按 trit 独立跳跃计算而不必逐格线性递推;同样的技巧原则上
可以下沉到块内部,按需只算被访问的那几格,而不是物化整块 59,049 格。
这是 backlog H1 里提到的"块内 memoryview"之外的另一个更根本的优化点,
值得单独立项。

## 3. mc2mb 基准(纯 Python 汇编,`assemble_mc_to_mb`,进程内调用)

5 档 `.mc` → `.mb`,按输出体积递增排列(python3.14,best_of_2):

| 用例 | .mc 源体积 | .mb 输出体积 | best_of_2 耗时 |
|---|---|---|---|
| mg_a_minimal.mc | 401 B | 176,251 B | 4.5177 s |
| mg_c_echo.mc | 579 B | 185,651 B | 7.0172 s |
| mg_b_hi.mc | 1,251 B | 293,563 B | 15.5586 s |
| mg_d_repeat.mc | 1,759 B | 467,087 B | 20.0844 s |
| mg_e_call.mc | 4,047 B | 799,471 B | 43.7802 s |

**幂律拟合**(对 `.mb` 体积 vs. 耗时做 log-log 最小二乘):指数 ≈ **1.36**
(首尾两点直接算得 ≈1.50)。也就是说内部研究日志(private,非本仓库)
§C 节里"近线性、约 40s/MB"的描述**需要修正**——耗时增长明显快于线性(体积 4.54× → 耗时
9.68×),按 O(n^1.36) 估算,20 MB 端到端冒烟用例(15.5 分钟)若继续按此
指数外推,体积每翻倍耗时约 ×2.6 而非 ×2,量级越大低估越严重。

## 4. mc2mb cProfile 剖析(mg_d_repeat.mc,.mb 输出 467,087 B,即上表中等档)

```
97,917,507 function calls in 38.123 s
tottime  cumtime  函数
0.043    37.429   mc2mb.py:904  dm_move()                          (51,884 次)
37.321   37.321   mc2mb.py:886  dm_mov_search()                (94,794,662 次!)
0.019    37.204   mc2mb.py:957  dm_accs2()                         (25,954 次)
0.011    37.140   mc2mb.py:1148 code_search() / code_generate()
0.013    36.989   mc2mb.py:941  dm_move2()
0.189    0.603    mc2mb.py:1512 finish()
```

（注:cProfile 逐调用记录的开销在 9500 万次调用规模下相当可观,故这里
的 38.123 s 明显高于 §3 无 profiler 下该用例的 best_of_2 20.0844 s——
两者差值即 profiler 自身开销,不代表回归;函数占比结构不受此影响。）

**头号热点**:`dm_mov_search()`——D 寄存器移动路径搜索,固定深度 3、
每层最多分支 100(`for i in range(d, 100)`)的**无记忆化递归搜索**,
这一档用例被调用近 **9500 万次**,占总运行时 **97.9%**。这是 D-寄存器
每次"移动到目标位置"(`dm_move`,51,884 次调用)时都要重新算一遍最短
跳转路径。

**关键结构性事实**:通读 `_Assembler.jmpaddrs` 的写入点(`grep
"jmpaddrs\["`),它只在 `setup_data_module()` 阶段被赋值(约 40 处固定
写入,与程序大小**无关**),在真正大量调用 `dm_move`/`dm_mov_search`
的 `code_generate()` 阶段 `jmpaddrs` 是**只读、恒定**的。这意味着
`dm_mov_search(d, pos, depth)` 在这一阶段是关于 `(d, pos, depth)` 的
**纯函数**——`d`、`pos` 的取值空间很小(`d` ∈ 0..99,`pos` 由代码生成
逻辑决定,depth ∈ 0..3),而调用发生了近亿次,说明存在海量重复子问题。
这正好解释了 §3 观察到的超线性增长:程序越大,`jmpaddrs` 中被占用的槽位
越多(见 `setup_data_module` 中 ~40 条写入,但实际运行中动态 -1/赋值切
换),递归分支因子随之变宽,单次 `dm_mov_search` 调用树变大,叠加调用
次数本身也随程序变大而增长,两者相乘导致 O(n^1.4) 而非 O(n)。

**可优化性判断**:这是**移植自参考 C++ 实现的原始算法**(`init/dmod.cpp`
的搜索逻辑被逐字节忠实移植,保证了 `.mb` 输出字节级一致),算法复杂度
本身在 C++ 里因为绝对速度快而不明显,移植到纯 Python 后常数因子被放大
成了主要瓶颈。**加记忆化缓存(在 `(d, pos, depth)` 上,且仅在
`jmpaddrs` 不变的阶段生效/或用其快照做缓存 key)是零风险、不改变输出
的优化**——因为 `dm_mov_search` 在该阶段是纯函数,缓存不会改变任何返回
值,只会消除重复计算。据调用次数与命中重复度粗估,理论上可将这一项的
耗时从"秒级/十秒级"压缩到"毫秒级",是全流程目前性价比最高的单点优化。

## 5. PyPy 加速比:未知(未安装,间接判断)

没有直接测出数字。可给出的间接依据:

- 两个头号热点(`crazy()` 的定长小循环数值计算、`dm_mov_search()` 的
  深度受限递归+大量函数调用)都是 PyPy JIT 传统上表现很好的模式
  (紧凑数值循环、单态调用点的递归),文献/社区经验里这类纯 Python 数值
  与函数调用密集代码在 PyPy 下常见 **5–20×** 提速,不能替代实测但可作
  为量级参考。
- 若后续要真正标定,只需 `brew install pypy3.11` 后重跑本报告的
  `bench_interp.py` / `bench_mc2mb.py`(脚本已在临时目录,可直接复用,
  两个脚本均不依赖 CPython 专有特性)。

## 6. 三条优化路线的预期收益判断

| 路线 | 预期收益 | 说明 |
|---|---|---|
| 纯 Python 微优化(去 dict 化/局部变量绑定/减少属性查找) | **有限,约 1.2–1.5×** | 两个热点的开销主体是"重复做同一件事"(整块物化、无记忆化搜索),不是"每次操作稍慢";局部变量化等常规手法只能压缩常数因子,治标不治本。 |
| mypyc(编译现有 .py 为 C 扩展,类型不变) | **中等,预计 3–8×**,前提是先做算法修复 | 能消除 Python 解释开销/函数调用开销,对 `dm_mov_search` 这种高调用频次的递归特别有效;但如果不先加记忆化,mypyc 编译后的 O(n^1.4) 依然是 O(n^1.4),大用例仍会慢。**收益顺序应是:先修算法,再上 mypyc 巩固常数因子。** |
| Cython(需手工加类型标注) | **较高但工程成本也高,预计 5–15×** | 对 `crazy()` 的 20 次内层循环、`dm_mov_search` 的递归可以标注 `cdef int` 获得比 mypyc 更激进的收益,但需要维护 `.pyx`/构建链,和"全 Python 可 pip install 安装"的项目定位(B6 里刚完成的全栈 Python 化成果)有一定张力,需要评估是否值得为性能牺牲部分这一优势。 |

**结论**:语言层加速(mypyc/Cython)都应该排在**算法/缓存修复之后**,
否则是在为一个本可以消除的重复计算"加速引擎"。

## 7. 建议的下一步优化动作(单条)

给 `_Assembler.dm_mov_search` 加记忆化缓存(例如按 `(d, pos, depth)` 做
`dict` 缓存,在 `jmpaddrs` 阶段性质不变的窗口内复用;或更保守地在
`code_generate()` 开始前对 `jmpaddrs` 做一次快照校验,缓存 key 带上快照
哈希以绝对保证正确性)。这是唯一同时满足"零风险不改变 `.mb` 字节输出"
与"预期收益最大"(热点占比 97.9%,重复子问题证据充分)两个条件的动作,
应先于 SparseMemory 块物化优化和任何 mypyc/Cython 投入。

---

## 建议追加进内部研究日志(private,非本仓库)的条目草稿(未编辑该日志,供审阅后手工合并)

**§C 补充/修正**(现有"纯 Python 汇编(mc2mb)耗时…与 .mb 体积近线性,
约 40s/MB"一句需要修正):

> **纯 Python 汇编(mc2mb)的规模行为经 5 档数据(176KB–799KB 输出)
> log-log 回归复核,实为超线性,指数约 1.36–1.50(非此前认为的近线性),
> 即体积翻倍时耗时增长约 2.6× 而非 2×。根因见 §H 新增条目:`dm_mov_search`
> 无记忆化递归搜索,占运行时 97.9%,且是 `(d, pos, depth)` 上的纯函数
> (`jmpaddrs` 在该阶段只读),存在海量可缓存的重复子问题。**

**§H 新增 backlog 条目**(建议编号 H8,优先级应在现有 H1/H7 之上,
或直接并入 H7 并改写):

> **H8. mc2mb `dm_mov_search` 记忆化(零风险,预期收益最大)**:
> `malbolge/compiler/mc2mb.py:886` 的 `dm_mov_search` 在 `code_generate`
> 阶段是 `(d, pos, depth)` 的纯函数(`jmpaddrs` 此阶段不再变化),但
> 每次 `dm_move` 都重新做一次深度 3、分支上限 100 的递归搜索,单个
> 799KB 用例调用 9500 万次,占该阶段运行时 97.9%(cProfile 实测)。
> 加缓存不改变 `.mb` 字节输出,是当前性价比最高的单点优化,应先于
> SparseMemory 块物化优化(见下条)和 mypyc/Cython 投入。

> **H9. malbolge20 解释器:SparseMemory 块物化粒度过粗**:cProfile 显示
> 主解释循环本体只占运行时 4–9%,70–80% 花在 `_materialize_block()` 整块
> (59,049 格)物化 `crazy()` 填充,即使程序只访问块内极少数格子。已有
> `_block_seed_jump_map` 的跨块跳种子技巧原则上可下沉到块内部做按需
> 单格计算,避免整块预物化。

*(以上两条为草稿文本,是否、如何合并入内部研究日志由后续人工决定;
本报告本身不修改该日志。)*
