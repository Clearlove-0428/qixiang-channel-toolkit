# 启翔湖畔频道资料工具

把页面观察记录按帖子 ID 整理到本机，关联正文、图片、截图和已取得的评论，并提供复核、检索、统计导出和逐帖浏览入口。

本仓库由课程实践中使用的本地工具整理而来。仓库只提供代码和完全虚构的示例，不附实际频道资料。浏览器采集适配的是“启翔湖畔—西北工业大学”QQ 频道的现有页面结构；其他频道需要调整解析器和来源校验。

## 能做什么

- **资料管理**：导入页面观察 JSON，跨批按帖子 ID 合并，保留列表预览、详情、采集入口和时间依据。
- **页面记录**：使用独立浏览器登录后，按分区记录页面已经呈现的帖子；也可加载浏览器扩展手动补充。
- **媒体关联**：压缩保存图片与截图，保留帖子和文件的关系；图像含义需要另行查看。
- **人工复核**：填写类别、依据与备注，导出或导入复核 CSV；人工判断与模型候选分列。
- **分析导出**：固定 SQLite 快照，生成覆盖统计、候选类别、复核表和 SVG 图。
- **逐帖浏览**：从本地资料库或快照生成离线 HTML、帖子 JSONL 和图文评论对应表。
- **可选模型**：配置本机 Qwen 兼容 GGUF 权重及 llama.cpp 服务程序后，生成文字分类候选。基础功能无需模型。

## Windows 快速开始

准备 Python 3.12 或更新版本、Node.js 20 或更新版本。后台采集默认使用本机 Chrome；单纯导入、复核和导出不需要安装浏览器自动化组件。

在仓库根目录打开 PowerShell，安装依赖：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

随后双击 `打开资料管理.cmd`，或执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start_workspace.ps1
```

浏览器打开本机地址 `http://127.0.0.1:8765`。第一次启动会创建空的 `调研资料库`，并在本机生成采集连接令牌。

**先用虚构资料体验**：在页面中取消“保存并压缩图片”，选择 `examples/页面观察_虚构示例.json`。导入后查看“帖子复核”，填写一条类别，再到“研究与成果”保存分析版本。示例只有两条虚构记录，不会访问真实频道。

如果 8765 端口已运行另一份本工具，启动器会核对资料库路径并报告冲突。不要把原项目正在运行的页面当作新副本。

## 前台启动与其他系统

前台启动便于查看日志，也可以用 Ctrl+C 结束服务：

```powershell
.\.venv\Scripts\python.exe -X utf8 .\频道文本工具\research_library.py serve --no-browser
```

macOS / Linux 可以使用下列命令；这一发行副本尚未在这些系统实测：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r 频道文本工具/requirements.txt
npm ci
.venv/bin/python 频道文本工具/research_library.py serve --no-browser
```

## 使用后台采集与浏览器扩展

后台采集：在资料页面点击“打开采集浏览器登录”，由本人完成 QQ 登录；确认频道列表正常显示后，回到资料页面开始采集。可以设置总目标、每分区观察量和详情读取间隔。停止按钮结束采集任务，已有资料继续保留。

如果不用 Chrome，可在启动服务前设置浏览器种类：

```powershell
$env:QIXIANG_BROWSER_CHANNEL = 'msedge'
```

使用 Playwright 自带 Chromium 时，先执行 `npx playwright install chromium`，再把该变量设为 `chromium`。独立浏览器默认将登录配置保存在本次资料库的 `浏览器登录配置` 子目录。

手动扩展：先用默认端口 8765 启动服务，再在 Chrome / Edge 扩展管理页面开启开发者模式，加载 `频道文本工具/浏览器手动采集` 文件夹。服务会生成该文件夹内的 `local_connection.json`；没有启动服务前，仓库只有连接格式示例。服务重建令牌后，应重新加载扩展。

采集依赖页面结构和本人可见范围，登录限制或页面变化可能导致记录停止或缺失。详情和评论只包含实际取得的部分。图片的文件关联、OCR、模型概括和人工确认是不同工作，本工具没有内置全库 OCR 流程。

## 命令行常用操作

导入示例并查看数量：

```powershell
.\.venv\Scripts\python.exe -X utf8 .\频道文本工具\research_library.py import .\examples\页面观察_虚构示例.json
.\.venv\Scripts\python.exe -X utf8 .\频道文本工具\research_library.py status
```

生成逐帖浏览页及对应表：

```powershell
.\.venv\Scripts\python.exe -X utf8 .\频道文本工具\build_handoff_catalog.py --database .\调研资料库\资料库.sqlite3 --library-root .\调研资料库 --output .\调研资料库\逐帖资料
```

双击输出目录里的 `逐帖浏览.html` 即可查看。也可以把 `--database` 指向某次分析导出中的 `资料快照.sqlite3`。图片和截图通过本机相对路径引用；单独复制 HTML 不会把媒体一起带走。

只分析一个 JSON 文件、生成独立质量报告：

```powershell
.\.venv\Scripts\python.exe -X utf8 .\频道文本工具\analyze_posts.py .\examples\页面观察_虚构示例.json --output-dir .\调研资料库\示例分析
```

`parse_public_page.py`、`capture_public_snapshot.py` 与 `save_images.py` 还提供已有 HTML 解析、单页快照和图片保存命令，参数见各脚本的 `--help`。

## 配置本地模型（可选）

在启动服务前设置实际文件路径：

```powershell
$env:QIXIANG_MODEL_PATH = 'E:\models\your-qwen-model.gguf'
$env:QIXIANG_LLAMA_SERVER = 'E:\llama\llama-server.exe'
```

默认不指定 GPU 设备，GPU 层数为 0。需要时再设置 `QIXIANG_MODEL_GPU_LAYERS` 和 `QIXIANG_MODEL_DEVICE`。模型提示词与输出校验沿用 Qwen3.5 文字分类流程，输入限于主帖前 500 字和前两条已取得评论，含图短帖保留待判断。更换模型和运行程序后需要自行核对兼容性、速度与候选质量。发行副本验证中使用模拟响应，没有重新加载真实权重推理。

其他配置见 `.env.example`。程序读取当前进程的环境变量，**不会自动加载 `.env` 文件**。可以通过 `QIXIANG_DATA_ROOT` 修改默认资料目录，或用命令行 `--root` 显式指定；浏览器扩展仍采用默认端口 8765。

## 代码结构

```text
频道文本工具/
  research_library.py       本机资料库、HTTP 服务与命令行
  capture_bridge.py         采集接收、任务回执与图像队列
  background_*.cjs/.py      独立浏览器采集与进度管理
  local_model.py            可配置的本地模型候选分类
  research_exports.py      固定快照、统计与复核表
  build_handoff_catalog.py 逐帖资料与离线浏览页导出
  workspace_ui/            本机管理网页
  浏览器手动采集/           Manifest V3 扩展
  tests/                   Python 与 Node 测试
examples/                  完全虚构的两帖示例
scripts/                   测试入口
```

## 验证

Python 测试全部使用临时资料库与合成资料：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s .\频道文本工具\tests -p 'test_*.py' -v
```

Node 不需要浏览器的测试：`npm run test:unit`。

完整 Node 测试：`npm test`，默认调用本机 Edge。可通过 `QIXIANG_TEST_BROWSER_CHANNEL=chrome` 改用 Chrome。若需指定 Python，先设置 `PYTHON` 为虚拟环境解释器的绝对路径。浏览器测试拦截频道页面请求并返回合成 HTML，管理页测试启动自己的临时服务，不访问原项目资料库。

本机发行核验的实际结果见 `docs/验证状态.md`。合成页面、模拟模型与本机运行结果，不能代替真实平台复测或其他电脑验收。

## 上传仓库

上传本目录中的源码和说明即可。运行生成的资料库、连接令牌、浏览器登录配置、依赖目录与模型文件均列入 `.gitignore`。上传前也请检查 Git 的暂存文件列表，特别是自行指定到其他路径的输出。

仓库没有附实际帖子、评论、截图、头像、问卷、访谈、课程报告或演示文稿。按帖子整理的浏览页与 CSV 是研究资料，运行后留在本机，不能直接当作公开示例。

本次整理未代选开源许可证；上传个人仓库后，是否公开以及采用何种许可证，由仓库所有者决定。依赖由安装命令单独获取，其许可见各依赖包。更多交付范围见 `docs/文件范围.md`。
