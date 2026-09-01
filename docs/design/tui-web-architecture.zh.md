# 调试器 UI 架构:一个 ViewModel,两个渲染器

> [English](tui-web-architecture.md) | **中文**
>
> 写于 2026-08-28。为针对已导入的设计画布(`tui-redesign/`)重建调试器 UI 敲定结构,
> 同时让浏览器构建可以从同一个核心接入。状态:**设计阶段,部分已实现** ——
> `malbolge/view/` 或 `malbolge/tui/` 下目前还什么都没有。Roadmap 条目:
> `docs/research/roadmap.zh.md` P4「Debugger UI rebuild」。

---

## 1. 这份文档要解决什么问题

`malbolge/debug_tui.py` 是塞在单个文件里的 787 行。每个面板都直接持有
`MalbolgeDebugger`,自己调 `get_state()`(每次刷新 7 次调用,重设计落地后会变成 11 次),
其中三个还越过公开 API 直接伸手去碰 `debugger._mem` 和 `debugger._input_pos`。每个面板都靠
手工拼装 Rich markup 字符串来渲染,这就逼出了手动 `[` 转义——已经有一个 `escape_markup`
辅助函数,外加三处散落的 `.replace('[', '\\[')` 调用。

这种状况对一个渲染器来说还能撑住。对两个渲染器就撑不住了。

因此决定把 UI 拆成三层,并把平台边界放在一个**数据**接口上,而不是一个控件接口上:

```
malbolge/core.py · malbolge.py · malbolge20.py     engine
malbolge/debugger.py                               debug control
        │                                          (breakpoints, history, preview)
        ▼
malbolge/view/                     ★ ViewModel — pure Python, JSON-only
        │
        ├──▶ malbolge/tui/         Textual renderer  (canvas 1a / 1b / 1c)
        └──▶ web/                  Pyodide + real web controls (canvas pending)
```

两个渲染器共享的是**含义**("这个单元被写过 3 次"、"这一行是当前指令"、"这个断点已经命中过
3 次")。它们不共享的是**呈现**——终端和浏览器的布局能力互不兼容,把一种呈现层硬套到两者
身上只会让两边都变差。

## 2. `malbolge/view/` 的两条规则

这不是风格偏好,两条都由运行时强制。

**规则 1——`view/` 之下任何地方都不允许 `import textual`。** 浏览器构建是在 Pyodide 里跑
这一层的,Textual 在那里既不存在也没有意义。

**规则 2——每个 ViewModel 的返回值都必须能扛过 `json.dumps()`。** 浏览器构建把 Pyodide 跑在
一个 Web Worker 里(见 §5),Worker 之间的通信走 `postMessage`,也就是 structured clone。返回值
里意外混入一个 Rich `Segment`、一个 `Enum`,或者一个可调用对象,会在**运行时**而不是评审时
把浏览器构建搞崩。

规则 2 有一个立竿见影的具体后果:`Breakpoint.condition` 是一个 `Callable`,所以
`BreakpointView` 暴露的是 `has_condition: bool`,而永远不是那个判定谓词本身。`StopReason`
是一个 `Enum`,所以视图发出的是 `stop_reason.value`(一个 `str`)。写一个 `test_view_json.py`
对每个 ViewModel 断言 `json.dumps(view)` 是最廉价的守卫,也是交付物的一部分。

这算不上一条规则,但值得说一句作为附带结果:因为 ViewModel 都是纯数据,测起来用的是普通
pytest——不需要 Textual pilot,不需要终端。这是整个项目里并行度最高、验证成本最低的一层。

## 3. ViewModel 契约

六个 ViewModel,每个面板家族一个。下面的字段名是规范性的——TUI 和浏览器构建都要照着它写。

### 3.1 `RegisterView`

```python
{
  "a": int, "a_char": str,          # a_char: printable or "."
  "c": int, "d": int,
  "next_a": int | None,             # from preview_next_instruction()
  "next_c": int | None,
  "next_d": int | None,
  "step": int,
  "history_size": int,
  "output_len": int,
  "input_consumed": int,
  "input_total": int,
  "terminated": bool,
  "stop_reason": str,               # StopReason.value
}
```

### 3.2 `DisasmView`

```python
{
  "center": int,                    # C at snapshot time
  "window": [int, int],             # inclusive address range shown
  "rows": [
    {
      "addr": int,
      "raw": int,                   # mem[addr]
      "char": str,
      "legal": bool,                # 33 <= raw <= 126
      "opcode": int | None,         # None when not legal
      "mnemonic": str,              # "???" for unknown opcodes
      "effect": str,                # NEW: "d ← mem[d]", "c ← mem[d]", …
      "is_current": bool,
      "has_breakpoint": bool,
    }
  ],
}
```

`effect` 是新增字段。它是从 `OPCODE_HELP[opcode]["syntax"]` 推导出来的,不是每个渲染器
各自发明的——画布 1a 的 `eff` 列和浏览器构建必须显示同一个字符串。

### 3.3 `MemoryView`

```python
{
  "d": int, "c": int,
  "start": int, "count": int,
  "offset": int,                    # manual scroll offset relative to D
  "heat_max": int,                  # max heat within this window, for normalising
  "cells": [
    {
      "addr": int, "value": int, "char": str,
      "heat": int,                  # cumulative write count, see §4.1
      "is_d": bool, "is_c": bool,
      "just_written": bool,         # written by the step that produced this snapshot
    }
  ],
}
```

`heat_max` 是按窗口算的,不是全局的:热力图是相对当前屏幕上显示的内容来归一化的,否则一个
特别热的单元会把其他一切都压平成黑色。

窗口以 `d + offset` 为**中心** —— `start = d + offset - count // 2`,再 clamp 进地址
空间 —— 这也是单文件版 TUI 用的规则(`start_addr = center - half_cells`)。居中这件事
归这一层管,不归各个渲染器管:窗口若锚定*在* D 上,显示的全是数据指针前方那些从未执行过的
地址,恰好把热力图存在的理由——最近被写过的那些单元——藏了起来。(之所以记下来:第一版实现
照着当时含糊的规格字面理解,把窗口锚在了 D 上,结果窗口内每一个 heat 值都是 0。)

### 3.4 `TeachingView`

用同一份数据同时喂给画布 1b 和工程模式下的教学面板。

```python
{
  "terminated": bool,
  "will_terminate": bool,
  "opcode": int, "opcode_name": str,
  "syntax": str, "description": str,           # from OPCODE_HELP
  "opcode_calc": {"mem_c": int, "mem_c_char": str, "c": int, "opcode": int},
  "effects": [                                 # canvas 1b's "4 things happen"
    {"order": int,
     "kind": "register" | "memory" | "encrypt" | "io" | "note",
     "text": str,
     "detail": str | None}
  ],
  "encrypt": {"addr": int, "index": int,
              "old": int, "old_char": str,
              "new": int, "new_char": str} | None,
  "ternary": {"kind": "crazy" | "rotate",
              "a": [int], "b": [int] | None, "result": [int],
              "highlight_before": int, "highlight_after": int} | None,
}
```

`effects` 列表是画布 1b 渲染成编号徽章时所用的、有序且枚举过的形式;工程模式把同一份列表
渲染成紧凑的文本行。顺序由 ViewModel 定义,不由任何一个渲染器自行决定。

### 3.5 `TimelineView`

```python
{
  "current": int,
  "max_reached": int,
  "seekable": [int, int],           # inclusive; bounded by the history window, §4.3
  "marks": [{"addr": int, "kind": "breakpoint" | "watchpoint"}],
}
```

### 3.6 `BreakpointView`

```python
{
  "breakpoints": [
    {"addr": int, "mnemonic": str, "hit_count": int,
     "enabled": bool, "temporary": bool, "has_condition": bool}
  ],
  "watchpoints": [
    {"addr": int, "enabled": bool, "last_value": int | None}
  ],
}
```

`Watchpoint` 目前没有 `hit_count`;画布 1a 也没有展示这个字段,所以这里不加。

### 3.7 快照

这六个 ViewModel 都是在状态每变化一次时,从单个 `DebuggerSnapshot` 一次性构建出来的,而不是
按需各自独立构建。这正是防止在时间线拖拽期间出现"帧撕裂"的关键——拖拽时每个 drag 事件都会
触发一次重建,如果采用"每个面板各自请求自己那份数据"的模型,就会出现反汇编停在第 900 步、
而内存面板还停在第 380 步的情况。

```python
def build_snapshot(dbg, *, mem_offset=0, mem_count=24, disasm_count=11) -> dict:
    """Returns {"registers": …, "disasm": …, "memory": …,
                "teaching": …, "timeline": …, "breakpoints": …}"""
```

## 4. 后端新增(`debugger.py`)

三处新增,都在 `debugger.py` 里,都由 `test_debugger.py` 覆盖。

### 4.1 内存写入热度

```python
@property
def write_heat(self) -> Mapping[int, int]: ...
def get_write_heat(self, start: int, count: int) -> list[int]: ...
```

统计对 `mem[addr]` 的每一次赋值——包括每步都会发生的 ENCRYPT 重写,以及 `crz` /
`rotr` 的写回。`_save_history` 本来就会为每一步收集一个 `mem_changes` 字典,所以这个计数器
只是挂在它旁边的一个小型累加器。对从未写过的地址,`get_write_heat` 返回 0,而不是抛异常。

重置语义:`reset()` 会清空热度。`step_back()` 会**递减**热度,这样热度能保持和可达的时间线
一致,而不是把已撤销的操作也算进去。

### 4.2 可中断的分块运行

```python
def run_chunked(self, chunk: int = 5000) -> Iterator[MalbolgeState]:
    """Yield the current state every `chunk` steps. The caller may stop
    iterating at any time; stopping does not corrupt debugger state."""
```

这是 Pyodide 要求的——浏览器构建在每个 worker 里是单线程的,一次同步的、动辄十万步的
`run()` 会把整个页面冻住,连停止按钮都按不了。**这同时也是给 TUI 修的一个 bug**:
`action_run` 目前调用的是 `run(max_steps=100000)`,终端 UI 在这期间是冻结的,只是至今没人
抱怨,因为终端把这一点掩盖得很好。

`run(max_steps=…)` 保持它现在的签名和行为完全不变,只是改为基于 `run_chunked` 重新实现。

### 4.3 时间线跳转

```python
@property
def max_step_reached(self) -> int: ...
@property
def seekable_range(self) -> tuple[int, int]: ...
def seek(self, step: int) -> MalbolgeState: ...
```

`seek` 在目标落在历史窗口内时用 `step_back` 往回走,否则用 `step` 往前走。当
`step > max_step_reached` 时抛 `ValueError`。

**这个窗口是真实存在的,而设计画布对它视而不见。** `debugger.py:271` 把 `_max_history` 钉在
10000,`_save_history` 一超过这个数就丢掉最旧的条目,而画布 1a 的时间线显示的却是
`380 / 1.2M`。决定:**采用窗口式方案(方案 A)**——时间线按完整范围画出来,但只有
`seekable_range` 部分可以拖拽,其余部分渲染成不可交互的样子。这样做诚实,而且不花什么代价。

另一种方案(周期性做全内存 checkpoint,从最近的一个重放)被推迟为一项独立的调研:它的成本
取决于 Malbolge20 的 `SparseMemory` 快照到底有多贵,而这是一个还没测过的数字,不能拿来卡住
这项工作。

## 5. 渲染器

### 5.1 TUI——`malbolge/tui/`

```
malbolge/tui/
  __init__.py      re-exports run_tui, main, DebuggerApp
  app.py           engineering-mode Screen (canvas 1a)
  theme.py         semantic colour tokens + CSS
  screens/
    help.py        HelpScreen (moved verbatim)
    teaching.py    teaching-mode Screen (canvas 1b)
  panels/
    base.py        shared markup escaping
    registers.py  disasm.py  memory.py  io.py  status.py
    breakpoints.py  timeline.py  command.py  source.py     (new)
```

`malbolge/debug_tui.py` 会缩成一个六行的垫片,重新导出 `run_tui`、`main` 和
`DebuggerApp`。它**不会**被删除:`malbolge/__main__.py:90` 和 `malbolge/debug_cli.py:587`
都从它那里 import,而且这个名字在 CLAUDE.md 和 README 里都出现过。斩断这条路径没有任何
好处。

已经拍板的决定,连同理由一起保留下来,因为这些决定将来会被重新拿出来吵:

| 问题 | 决定 | 理由 |
|---|---|---|
| 刷新粒度 | 分级:普通操作全量刷新,拖拽或运行期间只刷新轻量面板。结构上留出了做反应式依赖集的空间,但暂不去实现它 | 一旦有了拖拽,"全部刷新一切"会有肉眼可见的卡顿;而给 11 个面板建一整套反应式依赖图是实打实的工作量,目前还没有测量数据支撑要不要做 |
| 渲染方式 | 混合:文本类面板继续用 Rich markup;图形类面板(热力图、时间线、三进制网格)实现 `render()`,返回一个 Rich renderable | 用字符串拼一个 96 格的彩色网格,既不可读也没法测试,而且彻底绕开了 `[` 转义问题 |
| 1a 与 1b | 两个独立的 `Screen`,用 `Tab` 切换 | 它们的面板集合几乎没有重叠;塞进一个 Screen 的话,`compose()` 会写满条件判断。共享的是快照这份状态,而不是 Screen 本身 |
| 1c(80×24) | **不是**一个响应式 CSS 问题 | 把三列收缩成 `1`–`5` 几个 tab,是信息架构层面的变动,不是布局微调。需要一个能在宽屏时展开成多列的 `TabbedContent`。这是难度最高的一块,单独占一个阶段 |
| 颜色 | `theme.py` 只暴露语义化的 token(`CURRENT`、`BREAKPOINT`、`WATCHPOINT`、`WRITTEN`、`DIM`、`ACCENT`);面板永远不写字面颜色值 | 现在的四种边框颜色(`$primary/$secondary/$accent/$success`)不带任何语义。三个画布共享一套调色板;分散到 11 个文件里就会逐渐跑偏。这样做还能让"再加一套浅色主题"变成只改一个文件的事 |

源码面板(画布 1a,左侧列,`PYTHON` / `.mal` / `.mg` 几个 tab)会以一个**标注"未接入"的
占位符**形式出场:编译器目前不产生任何行映射或调试元数据,所以 py→mg→mb 的溯源信息根本
就不存在,自然也无从展示。构建这部分应该跟 `mb-dialect-plan.zh.md` 里的 IR 工作放在一起做,
而不是放在这里。

### 5.2 Web——`web/`(设计画布待定)

形态:**Pyodide,完全静态**,不需要服务端。这个包是纯 Python,不含 C 扩展,所以能原样
加载进 Pyodide,并直接托管在 GitHub Pages 上。

结构,尚未构建:

- Pyodide 跑在一个 **Web Worker** 里;主线程只负责渲染。这正是规则 2 之所以关键的原因。
- worker 恰好只暴露 §3 里的快照,加上命令接口(step / back / run / seek / breakpoint /
  watchpoint)。
- **v1 只支持原版 Malbolge**(59,049 个单元)。Malbolge20 那 34.8 亿单元的稀疏内存,
  在浏览器堆上的行为需要先测出数据,才能拿来承诺。

刻意悬而未决的部分是:视觉语言。`tui-redesign/` 这个画布是照着终端的形状设计的——等宽字体、
深色、80×24 约束、字符块拼出的热力图。把它原样搬到浏览器上,只会做出一个假终端网页,那还不如
直接用 `textual-web` 把真正的 TUI 端出去。一个真正的网页构建需要自己的画布,实现要等它出来
再说。

## 6. 阶段划分与可并行的边界

排序上的约束:`debug_tui.py` 目前**零测试覆盖**(`test_debugger.py` 只覆盖后端)。在没有
回归网的情况下把一个 787 行的文件拆给好几个 agent,再在同一趟里顺手改行为,正是悄无声息引入
破坏的典型方式。

| 阶段 | 工作内容 | 可并行? |
|---|---|---|
| 0a | 把 `debug_tui.py` 拆到 `malbolge/tui/` 下,行为逐字节不变,原地留一个垫片 | 串行 |
| 0b | `test/test_debug_tui.py`——用 Textual 的 `App.run_test()` pilot 写冒烟测试,钉住现有的按键行为 | 与 0a 并行(新文件,且 0a 保留了 import 路径) |
| 1 | 后端 §4 · `view/` 的 ViewModel §3 · 反汇编面板 · 新面板(breakpoints / timeline / command) · 教学 Screen | 可以——都是互不相干的文件 |
| 2 | 内存热力图(依赖 §4.1) · 布局、主题、1c 的 tab | 在 1 之后串行 |
| 3 | Web 构建 | 卡在它的设计画布上 |

`view/` 是整个项目里并行度最好的一块:纯数据,普通 pytest,不需要终端,而且契约在 §3 里
已经在任何人动手之前就定死了。

## 7. 未决问题

1. **`view/` 的粒度。** 是按面板家族分六个 ViewModel(如规格所写),还是按数据域分三个
   (执行状态 / 内存 / 元数据)? 六个的方案和画布对得上,agent 之间的边界也干净;三个的方案
   在快照构建器里重复更少。目前:六个。
2. **带 checkpoint 的时间线**(§4.3)——在能被排进日程之前,需要先测出 Malbolge20
   `SparseMemory` 做快照的成本。
3. **Web 视觉语言**——卡在一个设计画布上。
4. **把 `textual-web` 当副产品捎带出来。** 一旦 TUI 重建完成,这几乎是免费的,在网页画布
   还不存在的这段时间里也是个说得过去的权宜方案。目前未排期。
