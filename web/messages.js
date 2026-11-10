// UI-only text, with matching English and Simplified Chinese entries.
// Keep markup in renderers; never use program text or backend errors as keys.
export const messages = {
  "m1": {
    "zh": "回退一步 (←)",
    "en": "Step back (←)"
  },
  "m2": {
    "zh": "⏮ 回退",
    "en": "⏮ Back"
  },
  "m3": {
    "zh": "单步执行 (→)",
    "en": "Single step (→)"
  },
  "m4": {
    "zh": "⏭ 单步",
    "en": "⏭ Step"
  },
  "m5": {
    "zh": "继续 / 暂停 (F5)",
    "en": "Continue / Pause (F5)"
  },
  "m6": {
    "zh": "▶ 继续",
    "en": "▶ Continue"
  },
  "m7": {
    "zh": "每个运行分块的步数。worker 在分块之间才检查停止请求，块越大越快、响应越钝。",
    "en": "Steps per run chunk. The worker checks stop requests between chunks; larger chunks can reduce responsiveness."
  },
  "m8": {
    "zh": "重置到第 0 步",
    "en": "Reset to step 0"
  },
  "m9": {
    "zh": "⟲ 重置",
    "en": "⟲ Reset"
  },
  "m10": {
    "zh": "反汇编",
    "en": "Disassembly"
  },
  "m11": {
    "zh": "地址",
    "en": "Addr"
  },
  "m12": {
    "zh": "字符",
    "en": "Ch"
  },
  "m13": {
    "zh": "原值",
    "en": "Value"
  },
  "m14": {
    "zh": "助记符",
    "en": "Op"
  },
  "m15": {
    "zh": "效果",
    "en": "Effect"
  },
  "m16": {
    "zh": "把窗口拉回 D 附近",
    "en": "Return the window to D"
  },
  "m17": {
    "zh": "内存写入热力图",
    "en": "Memory-write heat map"
  },
  "m18": {
    "zh": "热度归一化方式。线性 = heat / heat_max（契约字面读法）；",
    "en": "Heat normalization. Linear = heat / heat_max; "
  },
  "m19": {
    "zh": "对数 = log1p(heat)/log1p(heat_max)。真实程序里单格写入次数相差上千倍，",
    "en": "log = log1p(heat)/log1p(heat_max). Write counts may vary by thousands; "
  },
  "m20": {
    "zh": "线性会把除最热一格外的所有格子压成纯黑。",
    "en": "linear scaling can make all but the hottest cells appear black."
  },
  "m21": {
    "zh": "内存 · 写入热度",
    "en": "Memory · Write heat"
  },
  "m22": {
    "zh": "冷",
    "en": "Cold"
  },
  "m23": {
    "zh": "D 指针",
    "en": "D pointer"
  },
  "m24": {
    "zh": "C 指针",
    "en": "C pointer"
  },
  "m25": {
    "zh": "本步写入",
    "en": "Written this step"
  },
  "m26": {
    "zh": "展开讲解 ↗",
    "en": "Explain ↗"
  },
  "m27": {
    "zh": "寄存器",
    "en": "Registers"
  },
  "m28": {
    "zh": "下一步预演",
    "en": "Next-step preview"
  },
  "m29": {
    "zh": "断点 · 监视点",
    "en": "Breakpoints · Watchpoints"
  },
  "m30": {
    "zh": "这段历史已被丢弃，不可回溯",
    "en": "This history was discarded and cannot be restored"
  },
  "m31": {
    "zh": "时间线位置（仅可回溯区间）",
    "en": "Timeline position (retained history only)"
  },
  "m32": {
    "zh": "时间线",
    "en": "Timeline"
  },
  "m33": {
    "zh": "输出",
    "en": "Output"
  },
  "m34": {
    "zh": "(未命名)",
    "en": "(unnamed)"
  },
  "m35": {
    "zh": "步 ",
    "en": "Step "
  },
  "m36": {
    "zh": "历史 ",
    "en": "History "
  },
  "m37": {
    "zh": " · 输入 ",
    "en": " · Input "
  },
  "m38": {
    "zh": "⏸ 暂停",
    "en": "⏸ Pause"
  },
  "m39": {
    "zh": "▶ 继续",
    "en": "▶ Continue"
  },
  "m40": {
    "zh": "教学视图（设计稿 1b）在 v1 范围之外，尚未构建",
    "en": "Teaching view is outside v1 scope and has not been built"
  },
  "m41": {
    "zh": "打开教学视图",
    "en": "Open teaching view"
  },
  "m42": {
    "zh": "▶ 运行中",
    "en": "▶ Running"
  },
  "m43": {
    "zh": "■ 已终止",
    "en": "■ Terminated"
  },
  "m44": {
    "zh": " · 第 ",
    "en": " · hit "
  },
  "m45": {
    "zh": " 次",
    "en": ""
  },
  "m46": {
    "zh": "⏸ 断点 @",
    "en": "⏸ Breakpoint @"
  },
  "m47": {
    "zh": "⏸ 监视点命中",
    "en": "⏸ Watchpoint hit"
  },
  "m48": {
    "zh": "⚠ 错误",
    "en": "⚠ Error"
  },
  "m49": {
    "zh": "⏸ 输入耗尽",
    "en": "⏸ Input exhausted"
  },
  "m50": {
    "zh": "已暂停",
    "en": "Paused"
  },
  "m51": {
    "zh": "已暂停",
    "en": "Paused"
  },
  "m52": {
    "zh": " · 跟随 C ◉",
    "en": " · Follow C ◉"
  },
  "m53": {
    "zh": "反汇编窗口恒以 C 为中心（ViewModel 未提供偏移量），无法脱离跟随",
    "en": "Disassembly is always centered on C; the ViewModel does not expose an offset."
  },
  "m54": {
    "zh": "移除断点",
    "en": "Remove breakpoint"
  },
  "m55": {
    "zh": "在此设置断点",
    "en": "Set breakpoint here"
  },
  "m56": {
    "zh": "移除",
    "en": "Remove"
  },
  "m57": {
    "zh": "设置",
    "en": "Set"
  },
  "m58": {
    "zh": "断点 ",
    "en": " breakpoint "
  },
  "m59": {
    "zh": "双击：把内存窗口移到此地址",
    "en": "Double-click to move the memory window here"
  },
  "m60": {
    "zh": "点击行首打点断点 · 双击地址跳到内存 · ",
    "en": "Gutter: breakpoint · Address: memory · "
  },
  "m61": {
    "zh": " 执行后改写为 ",
    "en": " becomes "
  },
  "m62": {
    "zh": "当前指令不触发加密改写",
    "en": "No encryption"
  },
  "m63": {
    "zh": "跟随 D",
    "en": "Follow D"
  },
  "m64": {
    "zh": "偏移 ",
    "en": "Offset "
  },
  "m65": {
    "zh": " 窗外 ↖",
    "en": " outside ↖"
  },
  "m66": {
    "zh": " 窗外 ↘",
    "en": " outside ↘"
  },
  "m67": {
    "zh": " 窗内",
    "en": " inside"
  },
  "m68": {
    "zh": "，写入 ",
    "en": ", writes "
  },
  "m69": {
    "zh": " 次",
    "en": ""
  },
  "m70": {
    "zh": "热 · 峰值 ",
    "en": "Hot · Peak "
  },
  "m71": {
    "zh": " 次",
    "en": ""
  },
  "m72": {
    "zh": "对数刻度",
    "en": "Log scale"
  },
  "m73": {
    "zh": "线性刻度",
    "en": "Linear scale"
  },
  "m74": {
    "zh": "点击任一格固定选中 · ⇧点击设/撤监视点 · 滚轮上下翻页",
    "en": "Click to pin · Shift-click: watchpoint · Scroll to page"
  },
  "m75": {
    "zh": "已选",
    "en": "Pinned"
  },
  "m76": {
    "zh": "写入 ",
    "en": "Writes "
  },
  "m77": {
    "zh": " 次",
    "en": ""
  },
  "m78": {
    "zh": "◈ 已布设监视点",
    "en": "◈ Watchpoint set"
  },
  "m79": {
    "zh": "距 D ",
    "en": "From D "
  },
  "m80": {
    "zh": "不可打印",
    "en": "Non-printable"
  },
  "m81": {
    "zh": " 可打印",
    "en": " Printable"
  },
  "m82": {
    "zh": "值",
    "en": "Value"
  },
  "m83": {
    "zh": "写入",
    "en": "Writes"
  },
  "m84": {
    "zh": " 次",
    "en": " writes"
  },
  "m85": {
    "zh": "距 D",
    "en": "From D"
  },
  "m86": {
    "zh": "监视",
    "en": "Watch"
  },
  "m87": {
    "zh": " · 上次 ",
    "en": " · Previous "
  },
  "m88": {
    "zh": "✓ wp 已布设",
    "en": "✓ Watchpoint set"
  },
  "m89": {
    "zh": "点击固定 · ⇧点击设监视点",
    "en": "Click to pin · Shift-click: watchpoint"
  },
  "m90": {
    "zh": "代码指针",
    "en": "Code pointer"
  },
  "m91": {
    "zh": "数据指针",
    "en": "Data pointer"
  },
  "m92": {
    "zh": "下一步不改变该寄存器，或程序已终止",
    "en": "No next change, or the program has terminated"
  },
  "m93": {
    "zh": "程序已终止，没有下一步。",
    "en": "Program terminated; no next step."
  },
  "m94": {
    "zh": "下一步没有可展示的副作用。",
    "en": "No side effects to preview."
  },
  "m95": {
    "zh": "原 ",
    "en": "was "
  },
  "m96": {
    "zh": "尚未设置。点击反汇编行首打断点，⇧点击内存格设监视点。",
    "en": "None set. Click the disassembly gutter for a breakpoint; Shift-click a memory cell for a watchpoint."
  },
  "m97": {
    "zh": "停用",
    "en": "Disable"
  },
  "m98": {
    "zh": "启用",
    "en": "Enable"
  },
  "m99": {
    "zh": "把内存窗口移到此地址",
    "en": "Move memory window to this address"
  },
  "m100": {
    "zh": "临时",
    "en": "Temporary"
  },
  "m101": {
    "zh": "命中条件",
    "en": "Hit condition"
  },
  "m102": {
    "zh": "命中 ",
    "en": "Hits "
  },
  "m103": {
    "zh": "已停用",
    "en": "Disabled"
  },
  "m104": {
    "zh": "删除断点",
    "en": "Remove breakpoint"
  },
  "m105": {
    "zh": "把内存窗口移到此地址",
    "en": "Move memory window to this address"
  },
  "m106": {
    "zh": "上次 ",
    "en": "Previous "
  },
  "m107": {
    "zh": "启用",
    "en": "Enable"
  },
  "m108": {
    "zh": "已停用",
    "en": "Disabled"
  },
  "m109": {
    "zh": "删除监视点",
    "en": "Remove watchpoint"
  },
  "m110": {
    "zh": "全程 ",
    "en": "Total "
  },
  "m111": {
    "zh": " 步 · 当前 ",
    "en": " steps · Current "
  },
  "m112": {
    "zh": " · 已回溯 ",
    "en": " · Back "
  },
  "m113": {
    "zh": "灰色区域历史已丢弃，不可拖拽 · 需要更早状态请重置后重新运行",
    "en": "Gray history was discarded. Reset and rerun for earlier states."
  },
  "m114": {
    "zh": "全部历史仍在窗口内，整条时间线均可拖拽",
    "en": "All history retained; drag anywhere on the timeline"
  },
  "m115": {
    "zh": "历史已丢弃 · 不可达 · ",
    "en": "Discarded history · Available from "
  },
  "m116": {
    "zh": " 起可回溯 ▶",
    "en": " ▶"
  },
  "m117": {
    "zh": "◀ 不可达 · ",
    "en": "◀ Unavailable · From "
  },
  "m118": {
    "zh": " 起",
    "en": ""
  },
  "m119": {
    "zh": "第 ",
    "en": "Step "
  },
  "m120": {
    "zh": " 步",
    "en": ""
  },
  "m121": {
    "zh": "可拖拽区间 ",
    "en": "Seek range "
  },
  "m122": {
    "zh": "（最近 ",
    "en": " (last "
  },
  "m123": {
    "zh": " 步）",
    "en": " steps)"
  },
  "m124": {
    "zh": "运行中不可拖拽",
    "en": "Cannot seek while running"
  },
  "m125": {
    "zh": "尚无可回溯的历史",
    "en": "No history to restore"
  },
  "m126": {
    "zh": "ViewModel 的 marks 带的是内存地址而非步数，无法投影到时间轴上，故在此列出",
    "en": "ViewModel marks contain memory addresses, not steps; listed separately from the timeline."
  },
  "m127": {
    "zh": "标记(地址)",
    "en": "Marks (addresses)"
  },
  "m128": {
    "zh": "把内存窗口移到此地址",
    "en": "Move memory window to this address"
  },
  "m129": {
    "zh": " · 可回溯区起点(最近 ",
    "en": " · Retained history starts here (last "
  },
  "m130": {
    "zh": " 步)",
    "en": " steps)"
  },
  "m131": {
    "zh": " · 全程可回溯",
    "en": " · All history available"
  },
  "m132": {
    "zh": " · 最新 ▶",
    "en": " · Latest ▶"
  },
  "m133": {
    "zh": "这段历史已被丢弃（后端只保留最近 10,000 步），无法回溯到这里。",
    "en": "This history was discarded (only the last 10,000 steps are retained)."
  },
  "m134": {
    "zh": "步 ",
    "en": "Step "
  },
  "m135": {
    "zh": "未知错误",
    "en": "Unknown error"
  },
  "m136": {
    "zh": " 字符",
    "en": " chars"
  },
  "m137": {
    "zh": "快照未携带输出文本（只有 output_len = ",
    "en": "Snapshot has no output text (output_len = "
  },
  "m138": {
    "zh": "尚无输出",
    "en": "No output yet"
  },
  "m139": {
    "zh": "显示最后 ",
    "en": "Showing last "
  },
  "m140": {
    "zh": " / 共 ",
    "en": " of "
  },
  "m141": {
    "zh": " 字符",
    "en": " chars"
  },
  "m142": {
    "zh": " 字符",
    "en": " chars"
  },
  "m143": {
    "zh": "更早的 ",
    "en": "Earlier "
  },
  "m144": {
    "zh": " 个字符不在快照里",
    "en": " chars are not in this snapshot"
  },
  "m145": {
    "zh": "入门",
    "en": "Intro"
  },
  "m146": {
    "zh": "经典 Hello, World —— 观察加密改写最直观的一步",
    "en": "Classic Hello World: see self-modifying encryption one step at a time"
  },
  "m147": {
    "zh": "长循环",
    "en": "Long run"
  },
  "m148": {
    "zh": "步数很多,适合看时间线拖拽和内存热力图,但要等得起",
    "en": "A long run for exploring the timeline and memory heat map"
  },
  "m149": {
    "zh": "带输入",
    "en": "Input"
  },
  "m150": {
    "zh": "需要标准输入,适合练断点与监视点",
    "en": "Requires input; explore breakpoints and watchpoints"
  },
  "m151": {
    "zh": " 单元",
    "en": " cells"
  },
  "m152": {
    "zh": " 步",
    "en": " steps"
  },
  "m153": {
    "zh": " 千步",
    "en": "k steps"
  },
  "m154": {
    "zh": " 万步",
    "en": " ×10,000 steps"
  },
  "m155": {
    "zh": "预计运行 ≈ ",
    "en": "Estimated run ≈ "
  },
  "m156": {
    "zh": " 秒",
    "en": " s"
  },
  "m157": {
    "zh": "预计运行 ≈ ",
    "en": "Estimated run ≈ "
  },
  "m158": {
    "zh": " 分钟",
    "en": " min"
  },
  "m159": {
    "zh": "读取版本信息…",
    "en": "Reading build metadata…"
  },
  "m160": {
    "zh": "Pyodide 运行时加载中…",
    "en": "Loading Pyodide runtime…"
  },
  "m161": {
    "zh": "解包 pyMalbolge…",
    "en": "Unpacking pyMalbolge…"
  },
  "m162": {
    "zh": "初始化 Python 环境…",
    "en": "Initializing Python…"
  },
  "m163": {
    "zh": "就绪",
    "en": "Ready"
  },
  "m165": {
    "zh": "载入示例 ",
    "en": "Load example "
  },
  "m175": {
    "zh": "示例列表加载失败(",
    "en": "Example catalog failed to load ("
  },
  "m176": {
    "zh": "),仍可手动粘贴代码运行。",
    "en": "); you can still paste code."
  },
  "m177": {
    "zh": "还没有代码 —— 拖入文件、粘贴代码,或点一张示例卡片。",
    "en": "No code yet. Drop a file, paste code, or choose an example."
  },
  "m178": {
    "zh": "未能加载示例 ",
    "en": "Could not load "
  },
  "m179": {
    "zh": ")—— 构建脚本可能还没有把 examples/ 复制到 web/vendor/examples/。",
    "en": "); the build may not have copied examples/ to web/vendor/examples/."
  },
  "m180": {
    "zh": "文件读取失败:",
    "en": "File read failed: "
  },
  "m181": {
    "zh": "输出 chr(a%256)",
    "en": "output chr(a%256)"
  },
  "m182": {
    "zh": "a ← 读入字符",
    "en": "a ← input character"
  },
  "m183": {
    "zh": "终止",
    "en": "Halt"
  },
  "m184": {
    "zh": "视作 nop",
    "en": "treated as nop"
  },
  "m185": {
    "zh": "不可执行 · 触碰即终止",
    "en": "invalid; halts"
  },
  "m186": {
    "zh": "可打印",
    "en": "Printable"
  },
  "m187": {
    "zh": "控制符",
    "en": "Control"
  },
  "m188": {
    "zh": "非 ASCII",
    "en": "Non-ASCII"
  },
  "m189": {
    "zh": "寄存器",
    "en": "Registers"
  },
  "m190": {
    "zh": "内存",
    "en": "Memory"
  },
  "m191": {
    "zh": "加密",
    "en": "Encryption"
  },
  "m192": {
    "zh": "输入输出",
    "en": "Input/output"
  },
  "m193": {
    "zh": "说明",
    "en": "Note"
  },
  "m194": {
    "zh": "运行中",
    "en": "Running"
  },
  "m195": {
    "zh": "已暂停",
    "en": "Paused"
  },
  "m196": {
    "zh": "断点",
    "en": "Breakpoint"
  },
  "m197": {
    "zh": "监视点",
    "en": "Watchpoint"
  },
  "m198": {
    "zh": "已终止",
    "en": "Terminated"
  },
  "m199": {
    "zh": "错误",
    "en": "Error"
  },
  "m200": {
    "zh": "输入耗尽",
    "en": "Input exhausted"
  },
  "m164_1": {
    "zh": "需输入",
    "en": "Input required"
  },
  "m166_1": {
    "zh": "Malbolge 调试器 —— 一门每走一步都会自我改写的语言,现在可以单步看清它",
    "en": "Malbolge debugger: explore a self-modifying language one step at a time"
  },
  "m167_1": {
    "zh": "纯静态 · 无服务器",
    "en": "Static · No server"
  },
  "m168_1": {
    "zh": "Python 跑在 Web Worker",
    "en": "Python in a Web Worker"
  },
  "m169_1": {
    "zh": "代码不离开浏览器",
    "en": "Code stays in your browser"
  },
  "m170_1": {
    "zh": "拖入 ",
    "en": "Drop a "
  },
  "m171_1": {
    "zh": "粘贴 Malbolge 代码",
    "en": "Paste Malbolge code"
  },
  "m171_2": {
    "zh": " 文件,或把代码粘贴到这里",
    "en": " file, or paste code here"
  },
  "m172_1": {
    "zh": "载入并调试",
    "en": "Load and debug"
  },
  "m173_1": {
    "zh": "仅可打印 ASCII;空白字符会被忽略",
    "en": "Printable ASCII only; whitespace is ignored"
  },
  "m174_1": {
    "zh": "首次加载需要联网 · v1 仅支持原始 Malbolge:3¹⁰ = 59,049 个内存单元",
    "en": "First load requires internet · v1 supports Original Malbolge only: 3¹⁰ = 59,049 memory cells"
  }
};
export const semanticMessages = {
  "输出 chr(a%256)": "m181",
  "a ← 读入字符": "m182",
  "终止": "m183",
  "视作 nop": "m184",
  "不可执行 · 触碰即终止": "m185",
  "可打印": "m186",
  "控制符": "m187",
  "非 ASCII": "m188",
  "寄存器": "m189",
  "内存": "m190",
  "加密": "m191",
  "输入输出": "m192",
  "说明": "m193",
  "运行中": "m194",
  "已暂停": "m195",
  "断点": "m196",
  "监视点": "m197",
  "已终止": "m198",
  "错误": "m199",
  "输入耗尽": "m200"
};
