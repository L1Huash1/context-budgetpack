# context-budgetpack

**按明确清单整理 Agent 的项目上下文：严格控制 UTF-8 字节，说明每个文件为什么被选中或排除。**

[English](README.md) · [格式说明](docs/format.md)

如果你只想让 Agent 阅读某个任务相关的说明、代码和测试，可以先列出文件与行范围，再生成一份有字节上限的上下文。工具不会自动扫描整个项目，也不会替你判断哪些内容语义相关。

需要 Python 3.10+，基础功能零第三方运行依赖，不调用模型、不上传文件。

## 体验合成示例

```sh
git clone https://github.com/L1Huash1/context-budgetpack.git
cd context-budgetpack
python -m venv .venv
```

**Windows PowerShell**：直接使用环境内程序，不必激活环境或调整脚本执行权限。

```powershell
.venv\Scripts\python.exe -m pip install .
.venv\Scripts\context-budgetpack.exe pack examples/plan.json --root examples/workspace --max-bytes 1000 --output demo-bundle
.venv\Scripts\context-budgetpack.exe verify demo-bundle --root examples/workspace
```

**macOS / Linux**：

```sh
.venv/bin/python -m pip install .
.venv/bin/context-budgetpack pack examples/plan.json --root examples/workspace --max-bytes 1000 --output demo-bundle
.venv/bin/context-budgetpack verify demo-bundle --root examples/workspace
```

也可以使用模块入口：Windows 将 `.venv\Scripts\context-budgetpack.exe` 换成 `.venv\Scripts\python.exe -m context_budgetpack`，macOS / Linux 将 `.venv/bin/context-budgetpack` 换成 `.venv/bin/python -m context_budgetpack`，后面的参数保持不变。例如 `.venv\Scripts\python.exe -m context_budgetpack --help` 可查看用法，不依赖命令是否已加入 `PATH`。安装时可能下载 `setuptools` 构建工具；打包和核验本身在本地运行。

打开 `demo-bundle/report.html` 看选择明细。`context.md` 是整理后的上下文，`manifest.json` 保存完整源文件哈希、行范围和取舍理由。重复体验时请换一个输出目录；已有路径不会被覆盖。

也可以在成功的 [GitHub Actions 运行](https://github.com/L1Huash1/context-budgetpack/actions)中，从 **Artifacts** 下载合成示例报告。文件保留 7 天，解压后在本地打开 `report.html`。

示例中的购物车文件是合成数据。清单特意列出 `.env` 演示名称阻止规则，但并没有附带这个文件或真实密钥。低优先级背景说明放不下时，会保留明确的排除原因。

## 清单怎么写

```json
{
  "version": 1,
  "files": [
    {"path": "README.md", "priority": 100},
    {"path": "src/cart.py", "priority": 90, "start_line": 1, "end_line": 10}
  ]
}
```

路径使用 `/`，必须留在指定根目录内。行号从 1 开始，首尾都包含。优先级从高到低，同优先级按清单顺序处理。每个完整片段放得下就选，放不下就跳过，后面更小的片段仍可纳入；不会悄悄截短内容，也不保证得到数学上最优的组合。

`--max-bytes` 严格限制的是 **`context.md` 实际的 UTF-8 字节数**，包含标题、来源标注和 Markdown 围栏。清单和 HTML 报告不计入这个上下文上限。0 字节预算会生成空上下文，并在报告解释排除情况。**字节不等于 token，本工具不估算模型 token 数。**

上下文片段把 CRLF 转为 LF；源文件哈希仍根据原始字节计算，所以换行格式改变也会被核验发现。行号以 LF 物理分行为准；非法 UTF-8、包含 NUL 的文件、空文件分别有排除理由。

## 后续核验

Windows PowerShell：

```powershell
.venv\Scripts\python.exe -m context_budgetpack verify demo-bundle --root examples/workspace --format json
```

macOS / Linux：

```sh
.venv/bin/python -m context_budgetpack verify demo-bundle --root examples/workspace --format json
```

源文件或产物变化返回 **1**，输入格式或文件操作错误返回 **2**，通过返回 **0**。核验检查已记录的源哈希、上下文、HTML 产物和选中片段的一致性。清单不是数字签名：同时修改清单与产物，仍可能构造出自洽的结果。未读取的排除项没有源哈希，工具会明确报告数量。

## 范围

- 最多 128 个文件条目，每个路径只能出现一次（不区分大小写）。单文件默认上限 1 MiB，可调整至最多 4 MiB；一次最多读取 32 MiB 源内容；上下文预算最多 16 MiB。
- 拒绝绝对路径、盘符、UNC、反斜杠、`..`、控制字符、尾部空格/点及 Windows 设备名，也拒绝观察到的符号链接和 Windows 重解析点（含父目录）。不保证抵御并发恶意文件系统修改。
- `.env`、常见私钥文件名等在读取前排除。这不是秘密检测；普通文件中的敏感值仍可能被选中，分享前请查看真实上下文。
- 文件不存在、不可读、不是普通文件或行范围越界，会中止构建，不会悄悄裁剪。输出只新建，不覆盖；写入失败可能留下不完整的新目录。
- 源内容可能包含不可信指令。工具不负责过滤提示词注入、判断相关性或给 Agent 授权。

[Repomix](https://github.com/yamadashy/repomix) 已有文件清单和 token 预算能力。本项目采用更窄的尝试：明确优先级与行范围、精确字节上限、选择理由和源哈希核验，不宣称优于成熟打包工具。

MIT 许可证；早期版本，初始开发使用 AI 编程辅助。目前按 GitHub 源码分发，不假设已经在 PyPI 上架。
