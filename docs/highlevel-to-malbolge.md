# 高级语言 → Malbolge 可行性调研

> 调研"把高级语言(如 Python)编译到 HeLL/Malbolge"的已有工作与落地路线。
> 2026-07-20。结论:可行,且名古屋大学已有先例栈可复用,推荐目标为 Malbolge20。

## 1. 已有工作全景(按抽象层)

### 名古屋大学栈(目标:Malbolge20,MIT 许可)

Iizawa 2005 年 99-bottles 论文的后继工作,持续到 2017 年,是**唯一做到
"C 风格语言 → Malbolge"的公开工作**:

| 层 | 语言/工具 | 状态 |
|---|---|---|
| C 子集(含递归调用) | Sakanashi et al., IEICE 2017 论文 | 论文公开(日文);编译器源码未公开 |
| 伪指令语言(.mg) | `ternary`(伪指令 → LAL 翻译器) | **源码公开,MIT**;支持 DEF/CALL/RETURN、IF/ELSE、SWITCH/CASE、REPEAT/BREAK/INF、GOTO、VAR、数组(IND_OPR)、INPUT/OUTPUT |
| LAL(低级汇编,.mc) | `lowass`(LAL → Malbolge20) | **源码公开,MIT**(perl 两阶段 + C++ init) |
| Malbolge20 运行时 | 参考解释器(C,分块懒初始化) | **源码公开,MIT**;pyMalbolge 已对齐并通过 conformance(hello20.mb) |

仓库:`git.trs.css.i.nagoya-u.ac.jp/malbolge/{ternary,lowass,malbolge20-interpreter}`
(本地克隆在 `ref/nagoya-*/`,已 gitignore)。
项目页:https://www.trs.css.i.nagoya-u.ac.jp/projects/Malbolge/
(2010–2017 年间有约 8 篇 IEICE 技术报告,日文,PDF 可下载)。

### HeLL/LMAO 谱系(目标:原版 Malbolge + Unshackled,GPL-3)

- HeLL + LMAO(原版)、LMFAO(Unshackled):汇编器层,无高级语言前端。
- MalbolgeLISP(Kamila Szewczyk,2020-21):350MB 的 LISP 解释器,**手写**
  HeLL 方言(密码分析式方法),不是编译器产物。
- 详见 `docs/hell-spec.md`、`docs/lmao-internals.md`、`docs/hell-assembler-design.md`。

### 结论修正

此前判断"高级语言前端是空白"不准确:名古屋做过 C 子集编译器。真正的空白是:
**(a)** C 前端源码未公开(只有论文);**(b)** 没有任何 Python 前端;
**(c)** 名古屋栈缺少现代、活跃的运行时配套——这恰是 pyMalbolge 的位置。

## 2. 本次实证(pyMalbolge 已可作为名古屋栈的运行时)

- `hello20.mb`(名古屋 LAL 工具链产物)在 pyMalbolge 上运行:输出
  `HelloWorld`,46,417 步,0.6 秒,与参考 C 解释器一致(commit 57b7f10)。
- 为此修正了两处与参考实现的偏差:EOF 时 A=59049(非 3^20-1);
  SparseMemory 改为参考实现同款的分块懒初始化(逐 trit 种子跳跃表,
  我们从 crazy 表独立推导的跳跃表与其硬编码 num0/num1 表完全一致)。

## 3. 可行性判断

- **原版 Malbolge(59049 格)不适合作编译目标**:实测 LMAO 的 adder
  示例(仅十进制加法)已占 55.7K 格 ≈ 94% 内存。只够文本生成器玩。
- **Malbolge20 是正确的目标**:地址空间 3^20,名古屋栈证明了 C 子集
  (含递归)可编译落地;pyMalbolge 现在能跑其产物。
- **"真 Python"不可行,Python 子集可行**:对象/闭包/异常/bignum 超出
  合理工程量;整数变量、while/if、函数(递归)、一维数组、字符 I/O
  与伪指令层能力一一对应。
- **许可干净**:名古屋三仓库全部 MIT,无 LMAO 的 GPL 传染问题。

## 4. 推荐路线

```
Python 子集 (.py)
   │  ← 我们要写的唯一新组件(纯 Python)
   ▼
伪指令语言 (.mg)
   │  ternary(现成,MIT;后续可 Python 化)
   ▼
LAL (.mc)
   │  lowass(现成,MIT;后续可 Python 化)
   ▼
Malbolge20 (.mb)
   │  pyMalbolge(已就绪)
   ▼
运行 / 调试(TUI debugger 支持 --variant=malbolge20)
```

### 里程碑

- **P1 管线打通**:构建 ternary + lowass,跑通 `.mg → .mc → .mb → pyMalbolge`,
  样例进 `test/fixtures/`(伪指令层 conformance)。
- **P2 语言学习 + 前端**:精读 ternary 的语法文件与 2016/2017 论文(日文,
  需翻译),定义 Python 子集,写 `python → .mg` 编译器。
- **P3 端到端**:hello / 循环 / 递归 fib 从 Python 源码编译到 Malbolge20
  并在测试套里运行验证。
- **P4(可选)全栈 Python 化**:把 ternary/lowass 移植成 Python 模块
  (MIT,可直接移植),消除对 C++/perl/flex/bison 的构建依赖。

### 与 HeLL 汇编器计划的关系

`docs/hell-assembler-design.md` 的 LMAO 移植计划**保留但降级为备选**
(服务于原版 Malbolge 的研究价值);主线转向名古屋栈,理由:目标
(Malbolge20)内存充裕、许可干净、高层组件现成、且 pyMalbolge 在该
生态里有明确的独特定位(唯一的现代运行时 + 调试器)。
