# Sandevistan Video

完全本地运行的 MiniMax H3 音画生成服务，提供中英文 Cyberpunk 风格网页和 HTTP API。适用于可信本机或局域网；当前没有账号认证，不应直接暴露到公网。

依赖锁、漏洞审计、CI 和升级发布流程见 [依赖管理](docs/DEPENDENCIES.md)。

## 使用

```bash
./scripts/setup.sh   # 首次安装：下载约 64GB 模型，需要联网
./service.sh start   # 后台启动，离开终端后继续运行
./service.sh status
./service.sh logs
./service.sh restart
./service.sh stop
```

网页：`http://localhost:20820`，API 文档：`http://localhost:20820/docs`。
服务监听 `0.0.0.0:20820`；从其他机器访问时，把 localhost 换成本机 IP。
ComfyUI 后端仅监听 `127.0.0.1:8188`。已有的 20810、20815 服务独立运行。

### 生成模式

| 模式 | 附图 | 用途 |
|---|---|---|
| `t2v` | 无 | 按文字生成带声视频 |
| `i2v` | 1 张 | 图片作为视频首帧，按描述运动 |
| `r2v` | 1–3 张 | 参考人物、物品、场景外观，生成新画面 |

每张图支持 PNG、JPEG、WebP，最大 15MB、2400 万像素。
首帧图片按输出画布居中裁剪；参考图保留宽高比。页面展示实际采用的图片。

时长可选 4–15 整秒，默认 5 秒。模型按 `5 + 17 × ceil((24 × 秒数 − 5) / 17)` 对齐帧数，因此 5、10、15 秒请求实际输出分别为 5.167、10.125、15.083 秒。输出为 24fps，20 步采样，包含立体声音轨。

增加时长也会增加潜变量、注意力和解码的资源需求，不能视为只增加耗时；实际峰值依赖模型卸载、分辨率和系统状态。
画质档位：`preview` 608×352、`standard` 864×480、`native` 1344×768。
默认使用已通过三种模式验证的 `native` 档。想快速试提示词可选择 `preview` 或 `standard`。
分辨率越高，内存占用和生成时间越长。当前机器的验证结果见文末。

### 提示词与声音设置

主输入框“画面、动作与对白”用于按镜头顺序描述主体、环境、动作、镜头、对白和同步现场声音。对白、歌唱、现场演奏或收音机中的音乐跟随动作写在主描述里；可选“声音设置”分别补充环境声与动作音效、仅观众听到的背景配乐。默认自然环境声、无背景配乐，界面会显示当前设置。选择自定义配乐后必须填写描述。

本地模板遵循 [H3 基础模式指南](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_base_en.md) 和 [参考模式指南](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md)：

- 文字生成：`integrated_multimodal_description`、`overall_soundscape`、`non_diegetic_music` 三段。
- 首帧生成：三段之前添加图片在 0 秒的首帧对齐说明。
- 外观参考：`subject_definitions`、`summary`、`retention_analysis`、`detailed_description`、`overall_soundscape`、`non_diegetic_music` 六段。
- 主描述不再被重复复制到参考模式的概要；不自动添加禁止对白的指令。无配乐使用 `non_diegetic_music: N/A`。

参考图按上传顺序显示编号，点击 `<Subject N>` 按钮可插入到主描述。每图可补充主体说明，例如按“人、篮球、咖啡杯”上传后，描述 `<Subject 1>` 坐在长椅上，`<Subject 2>` 位于脚边，人物举起 `<Subject 3>` 喝一口。普通表单采用一图一主体；完整编辑模式允许自定义一个主体与多张参考图之间的关系。

“最终提示词”可以预览、复制实际提交内容，预览与提交使用同一后端组装函数。可以从预览进入完整编辑，也可以直接“粘贴完整提示词”。完整编辑时按原文传递，包括首尾空白，不再追加分项设置；模式不匹配、缺失段落、图片引用越界等问题会提示，但不自动改写。返回表单会恢复之前的输入，完整草稿单独保留；“用当前预览更新完整草稿”会明确替换该草稿。

普通主描述最多 16000 字符，环境声与配乐各 4000，每图主体说明 1000。完整提示词最多 40000 字符，以便编辑和复用旧版合并后较长的提示词；字符限制不等同于模型的 token 容量。旧任务复用默认沿用已保存的最终提示词；返回描述表单可用原始输入套用新版模板。已排队及历史任务不会重新组装。

模板只在本地整理结构，不调用云端 Context-IR，不自动翻译、不识别图片内容、不补写剧情。页面提供中英文示例，建议正文使用英文，对白、歌词和画面文字保留原语言。声音验收包含音轨检查，逐字中文对白和精确口型同步不作保证。

## API 示例

```bash
curl -s http://localhost:20820/api/jobs \
  -F 'prompt=A small red toy car rolls across a wet stone path in a garden. The camera follows it in a continuous shot.' \
  -F 'soundscape=Gentle rainfall and faint wheel sounds.' \
  -F 'mode=t2v' -F 'preset=preview' -F 'duration_seconds=10' -F 'seed=42'

# 将返回的 id 填入以下地址
curl -s http://localhost:20820/api/jobs/JOB_ID
curl -o result.mp4 http://localhost:20820/api/jobs/JOB_ID/video
curl -X POST http://localhost:20820/api/jobs/JOB_ID/cancel

# 首帧模式
curl -s http://localhost:20820/api/jobs \
  -F 'prompt=The subject moves gently, with a slow camera push-in.' \
  -F 'mode=i2v' -F 'images=@photo.png'

# 外观参考模式：重复 images 字段上传多张图
curl -s http://localhost:20820/api/jobs \
  -F 'prompt=<Subject 1> is displayed on a wooden table in a sunlit garden.' \
  -F 'mode=r2v' -F 'images=@reference.png' \
  -F 'reference_descriptions=["The red toy car; preserve its shape and color."]'

# 只预览，不保存任务、不运行 GPU；image_count 是本次上传的图片数量
curl -s http://localhost:20820/api/prompts/preview \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"A cup lands on a table with a soft clink.","mode":"t2v","prompt_format":"guided","soundscape":"Quiet room ambience and a cup clink.","music":"Sparse piano notes at a slow tempo.","image_count":0}'

# 按原文提交完整提示词，不合并声音等分项设置
curl -s http://localhost:20820/api/jobs \
  -F 'prompt=<complete-prompt.txt' -F 'prompt_format=raw' -F 'mode=t2v'
```

`POST /api/jobs` 新增可选字段 `prompt_format`（`auto` / `guided` / `raw`）、`music`（空值表示无配乐）、`reference_descriptions`（Multipart 中为 JSON 字符串数组，按参考图顺序）。旧客户端默认 `auto`，仅当 `detailed_description:` 或 `integrated_multimodal_description:` 是独立段落标题时识别为完整提示词。完整提示词优先；同时传入分项设置时返回 `prompt_warnings`，说明这些设置未合并。

网页提交时额外使用 `text_encoding=json`，将 `prompt`、`soundscape`、`music` 编码为 JSON 字符串后放入 Multipart，避免浏览器自动转换换行；后端解码后与预览保持一致。直接调用 API 默认 `text_encoding=plain`，无需改变现有参数。

`POST /api/prompts/preview` 使用 JSON 接收上述字段、`mode`、`soundscape`、`image_count` 和可选 `source_job_id`；`reference_descriptions` 在 JSON 中直接使用数组。复用图片时不传新图片数量，由源任务确定数量；新图片数量优先。返回 `effective_prompt`、实际 `prompt_format`、`prompt_template_version` 和 `prompt_warnings`，正式任务保存同样的信息。`/api/capabilities` 提供各字段限制及模板版本。

提交立即返回 `202` 和任务 ID；通过 `/api/events` SSE 订阅进度，或低频查询任务接口。
任务列表继续返回数组，支持 `limit`、`offset`、`status`、`mode`、`search`，总数见 `X-Total-Count`。
状态为 `queued`、`running`、`succeeded`、`failed` 或 `cancelled`。
同时只执行一个 GPU 任务，最多另排队 8 个。
运行中的取消会等待当前计算响应中断，完成后再处理下一项任务。
排队任务持久化并在重启后恢复。API 单独重启时，通过预先持久化的后端任务 ID 接回进行中的任务；后端本身退出后，无法恢复的运行任务会明确失败，不自动重复生成，已有结果保留。

## 模型与资源

- Python 3.12，PyTorch 2.10.0 / CUDA 13.0。
- ComfyUI v0.35.0，提交 `40c4fcdf513a4523e39d54a9d391908af8df8171`。
- [Comfy-Org/MiniMax-H3](https://huggingface.co/Comfy-Org/MiniMax-H3)，固定模型 revision 记录在 `models/manifest.json`。
- FL2VA 和 Ref2VA 使用裁剪后的 INT8 ConvRot 权重，共用 NVFP4 AWQ 32B 文本编码器、FP16 视频 VAE、FP32 音频 VAE。
- 下载支持断点续传并校验官方 SHA-256；每个模型生成 `.verified.json` 校验记录。
- 启用动态显存、磁盘加载、禁用锁页内存，预留 3GB 显存。任务结束后释放模型。
- 安装完成后设置离线环境变量，禁用 ComfyUI 云 API 节点与第三方遥测。
- API 文档的 Swagger UI 资源也随项目保存在 `static/swagger/`，不依赖外部 CDN。
- 模型权重遵循其[上游许可证](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/LICENSE)。

## 数据与运行维护

| 位置 | 内容 |
|---|---|
| `models/` | 模型、校验记录和来源清单 |
| `data/jobs.sqlite3` | 任务记录 |
| `data/inputs/` | 标准化后的上传图片 |
| `data/outputs/<任务ID>/` | MP4、工作流、生成参数和资源指标 |
| `logs/comfy.log` | 模型加载与推理日志 |
| `logs/web.log` | 网页与 API 日志 |
| `logs/supervisor.log` | 后台进程日志 |
| `tmp/` | 上传与后端临时文件 |
| `cache/` | PyTorch、Triton、CUDA、Hugging Face 等可复用缓存 |
| `run/` | 进程身份、锁与模型路径配置 |

`service.sh` 使用独立监督进程、单实例文件锁和 PID 身份校验；同时监管 API 和推理后端。异常退出后递增延时重启，连续五次失败停止；稳定运行五分钟后重置失败计数。支持前台 `./service.sh run` 供外部进程管理器使用。

首次安装需要系统 Python 3.9+、Git、ffmpeg、Node.js 22.12+（推荐 24.21.0）；安装器下载并校验固定版本 uv/pnpm；前端构建后运行不需要 Node.js。原任务库自动备份迁移，独立验证产物的 metadata 会导入任务库。环境变量 `VIDEO_INTEL_HOST`、`VIDEO_INTEL_PORT`、`VIDEO_INTEL_BACKEND_PORT` 可覆盖监听配置；`VIDEO_INTEL_MIN_FREE_BYTES` 默认 5GiB，低于阈值拒绝新任务。
若生成失败，查看任务的 `error` 和 `logs/comfy.log`。服务不会自动降低用户选择的画质或更换模型。
成功任务的 `metrics` 包含总耗时、GPU 总占用峰值、后端 RSS 峰值和最低可用系统内存。
GPU 总占用包含桌面及其他程序，RSS 不等于模型文件总大小。

```bash
.venv/bin/python -m pytest tests -q
.venv/bin/ruff check video_intel tests scripts
```

## 本机验证

硬件：RTX 4090 Laptop 16GB，约 20GB RAM，无 Swap。验证日期：2026-09-15。
所有样片均为真实 H3 生成：124 帧、24fps、5.17 秒、20 步采样，使用固定种子 42。
耗时包含模型加载、生成、音画解码和 MP4 封装，不包含排队。

| 档位 | 文字生成 | 首帧图生视频 | 外观参考生成 |
|---|---:|---:|---:|
| 预览 608×352 | 1分21秒 | 1分34秒 | 1分39秒 |
| 标准 864×480 | 3分40秒 | 3分56秒 | 3分54秒 |
| 原生 1344×768 | 15分33秒 | 17分00秒 | 16分01秒 |

测试描述为红色玩具车在雨后花园中行驶；首帧取自已生成样片；
参考模式把同一辆敞篷玩具车放到阳光下的木质工作台。
三种模式都已生成真实带声样片，参考模式的抽帧检查确认车辆外观得到保留、场景成功改变。

详细生成参数、工作流、资源峰值和媒体属性保存在每条结果旁的 `metadata.json`、`workflow.json` 中。
`data/validation/` 保存验证记录和媒体检查结果，页面的“最近任务”可直接播放已生成样片。

九个组合均通过；显存总占用峰值约 **15.11GiB**（包含桌面），最低可用系统内存约 **9.85GiB**。
以上是本机样片实测，提示词、其他程序占用和硬件温度会影响耗时。

- 九条样片全部通过 ffmpeg 完整解码、双声道非静音检查和首尾画面变化检查。
- 14 项服务测试通过；实际采样中的取消得到确认，随后成功执行原生参考任务。
- Ruff 检查通过，127 个已安装依赖兼容。
- 另验证了三张参考图同时进入本地图片/文字编码链路。
- 使用 Playwright / Chromium 验证了桌面 1440×1000 和手机 390×844 页面：自动展示最近结果、历史选择、持续播放、实际 MP4 下载、离线 API 文档及文档内发起请求均通过；控制台错误、警告和外网请求均为零。未验证其他浏览器。

样片：[原生文生视频](http://localhost:20820/api/jobs/03547e0fbec94971b7ec44eb0db0c5d3/video) · [原生首帧视频](http://localhost:20820/api/jobs/ea03bad86d744b3f86b3c7745d7f2515/video) · [原生参考视频](http://localhost:20820/api/jobs/78ac55c113df46d1af9e02dceae9cf80/video)。

## 存储与 SSD 写入

主导航为“生成工作台 / 任务库 / 系统”。任务库统一管理任务与文件，支持占用列、最新/最早/占用从大到小排序、20/50/100 条分页、当前页批量选择；确认删除时显示数量与预计释放空间，部分失败会保留原因并支持重试。系统页的“存储维护”显示磁盘可用、任务文件和可清理运行残留，模型与环境另行折叠展示。每次清理先预览，再确认；执行时再次检查。结果默认永久保留，不按时间自动删除。删除任务会同时删除它的结果、输入、工作流和记录；运行、排队或正在下载的任务受到保护。模型、Python 环境和供应商代码不在清理范围内。

“清理运行残留”只处理终止任务的多余产物及空闲时的临时文件，保留正式视频与任务记录。管理任务文件会跳转到任务库的已结束任务，并按占用降序排列。缓存、滚动日志和数据库压缩位于高级清理；缓存和临时文件在生成、排队或上传时跳过，数据库压缩仅空闲时手动执行。缓存清理可能导致下次重新编译，通常无需频繁使用。

旧链接 `#storage` 自动跳转到 `#system/storage`，`#history` 对应任务库。磁盘不足时，生成表单提供任务管理与运行残留清理入口；本次页面会话内切换页面会保留参数及已选图片（整页刷新无法保留本地 File 对象）。

任务占用共用 60 秒内存缓存；任务状态变化、删除与手动刷新使统计失效，采样进度不会触发扫描。任务列表只统计任务所属目录，不扫描模型与依赖环境。`GET /api/jobs` 可传 `sort=newest|oldest|size_desc` 和 `include_storage=true`，大小排序在全局筛选结果上分页，默认响应仍为数组并保留 `X-Total-Count`；`GET /api/storage?include_jobs=false` 省略重复任务明细。低磁盘提交保持 HTTP 422 和字符串 `detail`，另返回 `code=insufficient_storage`。

进度在内存通过 SSE 推送；非关键状态最多每 60 秒写入数据库，关键状态立即提交。业务 SQLite 使用 WAL 与 FULL 同步；推理后端的辅助资产索引放在内存中，避免重复持久化。结果 MP4 直接同盘重命名，不再制作重复封装副本；每条结果只生成一张小预览图。日志每个文件 5MiB、保留 3 个滚动备份，API 访问日志关闭。缓存保留以减少重复下载和编译。第三方无法重定向的 OS 临时文件仍可能位于 `/tmp`。这些措施减少不必要的写入，不代表运行零写入或可直接计算物理 SSD 磨损。

前端开发与检查：

```bash
./scripts/pnpm.sh install --frozen-lockfile
./scripts/pnpm.sh build
.venv/bin/python -m pytest tests -q
.venv/bin/ruff check video_intel tests scripts
```

新版时长验收记录：`data/validation/production-results.json`。通过 `scripts/verify_production.py` 可恢复验收任务；它会真实消耗 GPU 时间。


## 生产版验收（2026-09-16）

| 请求 | 实际时长 | 分辨率 | 实测耗时 | 观测显存峰值 |
|---|---:|---|---:|---:|
| 首帧生成 4 秒 | 4.458 秒 | 608×352 | 1 分 21 秒 | 14.21 GiB |
| 参考生成 10 秒 | 10.125 秒 | 608×352 | 3 分 50 秒 | 14.27 GiB |
| 文字生成 15 秒 | 15.083 秒 | 1344×768 | 98 分 47 秒 | 14.55 GiB |

15 秒任务耗时采用后端日志；API 监测记录为 98 分 16 秒，重启恢复测试会遗漏重连之间的少量监测时间。

三条视频均通过完整解码、24fps 与帧数检查、双声道非静音检查和首尾画面变化检查。15 秒原生结果为 362 帧，视频 15.083 秒、音轨 15.075 秒；后台进程 RSS 峰值约 9.04 GiB，系统最低可用内存约 8.00 GiB。指标每 10 秒采样，GPU 总占用包含桌面；这不是其他提示词、硬件或更长时长的资源保证。

54 项后端测试、TypeScript/Vite 生产构建和 Ruff 检查通过。实际验证了运行中 API 重启接回相同任务、旧 SSE 序号重置、保持 SSE 连接时完整服务重启、18 条历史任务保留，以及内存资产索引下的后端图片保存。服务已恢复运行。

浏览器使用 Playwright + 系统 Chromium（当前无 Browser 插件），验证 1440×1000 桌面和 390×844 手机尺寸：四个页面、中英文切换、刷新保留表单、时长选择、替换复用图片、真实提交与取消、清理预览及测试任务删除、播放/拖动/下载、离线 API 文档均通过。控制台错误与外网请求为零；未验证 Safari、Firefox 或真实手机设备。

原始记录：`data/validation/production-results.json`、`production-media.json`、`recovery.json`、`sse-recovery.json`、`service-lifecycle.json` 和 `data/validation/ui/`。

[播放 15 秒原生样片](http://localhost:20820/api/jobs/772d6761a3b6422e98a966336975b9bf/video)。


## 任务库与存储维护验收（2026-09-17）

58 项后端测试、TypeScript/Vite 构建和 Ruff 检查通过。Chromium / Playwright 在 1440×1000 与 390×844、中英文界面上验证了三入口导航、旧链接跳转、占用排序、分页与选择重置、删除后空页回退、部分删除失败及重试、低磁盘入口、清理后的参数与图片保留。额外验证了新分页加载期间禁用旧行选择，避免误删上一页任务。删除与残留清理使用独立测试数据；生产服务 20820 的 18 条历史任务全部保留，实际播放、MP4 下载、清理预览通过，未发现应用控制台错误。截图位于 `data/validation/ux-refactor/`。未验证其他浏览器，也未重新运行 GPU 生成。
