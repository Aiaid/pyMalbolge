# OSP 固定实验入口

这组公开输入与 runner 用于冻结版本的验收和后续复现，不依赖私有研究资料。
完整参数、计时边界和命令见 [英文说明](README.md)。

- `manifest.json`：6 个程序、10 组输入。默认 smoke 仅含 3 个程序、4 组
  workload；standard 再覆盖循环与短路求值，all 再加双递归。
- `regressions.json`：3 个历史布局案例。检查正确输出、实际输入消耗和正常
  HALT，不沿用旧诊断测试中“应当失败”的断言。必须显式选择 all。
- `../manifest.json`：原有 12 个普通 Python 程序、32 组固定输入；同一 runner
  可直接运行。十进制输入输出会引入较大的辅助程序，不算低成本 smoke。

先检查输入 oracle：

```sh
uv run --no-sync python scripts/osp_experiments.py --mode oracle --suite all \
  --output-dir /tmp/osp-input-check
```

正式验收须指定 checkout 外安装环境，而不是只在源码目录测试：

```sh
uv run --no-sync python scripts/osp_experiments.py --mode run \
  --python /tmp/osp-installed/bin/python --expected-version 1.2.0rc1 \
  --forbid-source-root . --suite smoke --backends auto direct \
  --engines python --output-dir /tmp/osp-installed-smoke
```

1.2.0rc1 只是本地候选示例，不表示已发布；TestPyPI 构建应填写实际安装的
完整开发版本号。Windows 的 Python 路径改为环境下
`Scripts/python.exe`，输出目录改为本机路径。每次使用全新输出目录。

native 平台加 `--engines python native`；明确请求却不可用会失败，不会降级
成“通过”。IR 平台先安装对应版本的 ir extra，再添加 `--backends auto direct ir`。
用于论文复现的输入、代码和包 SHA-256、依赖版本、实际引擎、选中的 backend、
输出、输入消耗、HALT、steps、CPU/wall 时间分别记录在 JSON 中。

默认一次采样只用于验收。性能比较至少显式选择 `--repeats 3`，在同机控制
负载并保存全部样本；多平台 CI 不是跨机器速度排行榜。超时、不完整与失败
都保留，不能以 deadline 充当实际运行时间。论文若需要独立目标解释器验证，
保留 `--keep-images` 并使用既有 `verify_mb_reference.py`。

本目录不会把未执行的平台标为通过。Apple Silicon native、最低 OS、不同
Python ABI、纯 Python fallback 与可选 IR 都需要各自的真实证据。
