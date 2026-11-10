# 依赖管理与发布

## v1.0.3 升级

从已发布的 v1.0.2 升级：**无数据库迁移、历史文件改写或删除，无需额外升级备份**。先记录监听配置与进程身份，等待任务结束并停止服务；执行 `./scripts/setup.sh --skip-models` 同步锁定环境和前端，再恢复原有运行状态并核验历史任务、媒体和版本。已有模型保持原 revision，不重新下载。更早版本也须覆盖下方相应升级要求。

本版定向修复依赖告警，更新 Pillow 13.0.0、setuptools 84.1.0、Vite 7.3.7 等兼容版本及校验固定的 uv 0.13.4；完整版本见提交的锁文件。退役未接入现有服务入口的旧 `video_intel.ui` Gradio 模块及其依赖，现用 React 页面和 HTTP API 保持兼容。Torch、CUDA、Transformers、ComfyUI 提交、模型和推理参数不变。现有两项模型环境 Torch VEX 继续按各自复查日期管理，不代表组件漏洞已修复。

依赖安全审计每周一 04:23 UTC 独立运行；完整回归每月 1 日 04:43 UTC 运行，原提交、PR、标签和手动门禁继续执行。独立 browser 作业先构建自己的生产资源，避免已有构建产物掩盖干净 runner 的缺失。后端/前端版本及发布标签统一为 1.0.3，并增加标签版本契约，修正旧 v1.0.2 标签仍使用 1.0.1 应用元数据的不一致。

English: From published v1.0.2, no data migration, historical rewrite or additional upgrade backup is required. Stop the recorded instance, synchronize locked dependencies/build assets with setup.sh --skip-models, then restore and verify the original state. The legacy Gradio module is retired; React/API behavior and the validated inference stack remain. Release, frontend and API versions now agree. Earlier upgrades must include their intervening requirements.

支持 Linux x86_64、Python 3.12、CUDA 13.0。当前没有原生 Windows 或 CPU 部署配置。
生产运行仍使用项目 `.venv`；CI 使用独立的轻量环境，不下载模型或 CUDA wheels。

## 固定版本与安装

`scripts/toolchain.json` 是工具版本和下载校验值的来源：uv 0.13.4、pnpm 10.34.5、
pip-audit 2.10.1。Python 3.12.14 与 Node 24.21.0 是 CI 验证版本；现有 Python 3.12
环境可继续使用，Node 最低为 22.12。首次安装需要系统 Python 3.9+（启动安装器）、
Node、Git、ffmpeg；工具下载到 `.runtime/`，不安装到系统全局。

```bash
./scripts/setup.sh                # 首次安装、校验模型、构建前端
./scripts/setup.sh --skip-models  # 已有模型时，仅同步依赖和构建
./scripts/pnpm.sh install --frozen-lockfile
./scripts/pnpm.sh dev             # 只监听 127.0.0.1
./scripts/pnpm.sh build
```

从 v1.0.0 升级时停止服务，删除旧的生成目录 `frontend/node_modules/` 后重新安装，
避免旧 npm/pnpm 安装状态干扰脚本许可检查。不要删除模型或业务数据。
`scripts/pnpm.sh` 使用校验过下载完整性的项目本地 pnpm，不依赖全局 pnpm/Corepack。
只允许 esbuild 的依赖构建脚本，明确禁用 Swagger 的 Scarf 遥测脚本；未知脚本使安装失败。

Python 安装必须有完整锁文件，使用 `uv pip sync --require-hashes --strict`，删除环境中
未锁定的包，拒绝缺失或错误哈希。Torch 使用明确的 `cu130` backend；不使用跨仓库
`unsafe-best-match`，也不在锁文件安装之前单独安装 Torch。正常运行不访问模型仓库。

## 更新锁文件

`requirements-api.in`、`requirements-comfy.in`、`requirements-dev.in` 和 `requirements.in`
是依赖输入。ComfyUI 清单是固定提交的原始 requirements 快照，带 SHA256，CI 与上游
不可变提交核对。`requirements.lock` 是完整环境哈希锁；`requirements-ci.lock` 是 API
与开发工具哈希锁，其共同依赖受完整锁约束，避免测试环境与实际运行版本漂移。

```bash
python3 scripts/lock_dependencies.py
python3 scripts/lock_dependencies.py --check
# 仅更新指定依赖，保留无关版本：
python3 scripts/lock_dependencies.py --upgrade-package filelock==4.2.1
# 仅在明确更新间接依赖时使用；仍须重新审计与验证：
python3 scripts/lock_dependencies.py --upgrade
```

默认生成以已有锁文件为解析基线，只更新必须变化的包。`--check` 在临时目录重新生成
并比较，不改已提交文件；不能和 `--upgrade` 同用。输入与两份锁必须一起提交。
不要直接编辑生成锁来绕过依赖冲突。

前端仅使用 `frontend/pnpm-lock.yaml`，不再维护 package-lock.json。直接依赖固定版本，
通过 pnpm 显式更新并提交完整锁。不要例行升级 Vite 8、React 大版本或整个推理栈。

Swagger UI 固定为 5.32.15，纳入前端审计。`sync:swagger` 从锁定包复制 JS、CSS、LICENSE
并生成哈希清单；`check:swagger` 只检查。生产 build 包含检查但不重写这些已提交资源。
API-only 检查仍可使用 `/docs`，无需 Node 或前端构建，所有资源与 schema 保持本地加载。

## 安全审计与例外

```bash
.venv/bin/python scripts/audit_dependencies.py
```

审计完整 Python/CI 锁、前端锁、uv 和 pnpm 工具版本。Python 使用固定版本 pip-audit
查询 OSV；官方 `torch/torchvision/torchaudio` 的 `+cu130` 构建映射至相同基础版本查询，
报告同时保留安装版本。未知本地版本、被跳过或遗漏的包、查询失败都视为失败。
前端及工具不得有已知告警。报告默认写到忽略目录 `tmp/dependency-audit.json`。

已修复 Vite 的开发服务器问题，升级至 7.3.7，并固定 source-map-js 1.2.2；setuptools
升级至 84.1.0，修复 PackageIndex 路径穿越和 sdist Unicode 排除规则问题。

`dependency-exceptions.json` 只列当前推理部署边界内不适用的两个 Torch 公告：

- GHSA-rrmf-rvhw-rf47 / CVE-2025-3000：攻击者提供本地 Python 脚本给 `torch.jit.script`。
- PYSEC-2026-139 / CVE-2026-4538：攻击者提供恶意 `.pt2` 归档给加载器。

服务提交接口只接受文字和解码后的图片，不接受 Python、任意工作流或 checkpoint；H3
工作流和 safetensors 文件名由服务固定，下载器固定仓库 revision 并校验官方 SHA256。
ComfyUI 仅监听 loopback。这些依据不适用于不可信本机用户、单独暴露的 ComfyUI 或用户
手动加载其他模型；例外不是已修复声明，也不是对整个 PyTorch 的安全保证。

例外绑定包版本、ComfyUI 提交、模型 revision 和复查日期；不匹配、到期或公告已消失时
检查失败。新增公告必须调查后处理，禁止整包忽略、忽略不可修复项或忽略网络错误。
修改用户模型/代码输入边界时必须重新评估例外。本工具不替代完整源码安全审计，也不
宣称覆盖操作系统、驱动或上游未报告的漏洞。

## 验证、升级与发布

Linux CI 在 PR、main、版本标签、手动触发和每月 1 日 04:43 UTC 执行：锁校验、上游清单校验、pytest、
Ruff、生产构建、Vite 安全回归、依赖审计与无 GPU 浏览器检查。Actions 固定提交且只读权限。
浏览器使用隔离 API 数据、端口和目录，覆盖桌面/手机、中英文、导航与离线 Swagger。

发布必须通过同一 SHA 的 main CI 和标签 CI；标签不可移动或复用。更新后端及前端版本，
确认 OpenAPI 与健康接口版本一致。安全报告与截图由 CI 保存；GPU 验收单独在本机进行。

本次 v1.0.0 → v1.0.1 没有数据库或媒体迁移。维护前记录原配置、进程身份和任务状态，
等待活动任务完成，停止服务，再同步依赖。保留旧提交/依赖锁，更新失败时按旧锁恢复。
有数据迁移的后续版本应先做 SQLite 快照；重写媒体时同时备份相关文件。

恢复服务后核验新进程身份、实际配置、健康与版本、历史任务及媒体可读性。更改推理
依赖或安装方式必须运行真实生成，使用新的 `--manifest` 和 `--reference-image`，避免
复用旧成功记录；至少覆盖三种预览模式及一条原生分辨率样片。GitHub 发布与本地恢复
分别报告，失败时不宣称完成，也不靠挪动标签补救。

## 独立安全巡检与本轮升级

`Dependency security audit` 每周一 04:23 UTC 独立运行，也作为 Linux 完整检查的必需作业。backend/browser/security 分别执行，审计失败仍可取得功能与浏览器诊断；`linux` 汇总仅在三者全部成功时通过。发布仍要求同一 SHA 的 main 和标签完整门禁通过。

本地仍使用 `python scripts/audit_dependencies.py`；`--output` 指定完整 JSON 路径，同名 `.md` 为摘要。原有 status/date/python/accepted/rejected/frontend/tools 字段保留，新增分范围结果、UTC、触发类型和 SHA。报告完整锁、CI 锁、uv、前端和 pnpm，别名只在摘要归并。所有范围执行后统一判定；查询错误和未豁免公告均失败，超时/429/5xx 最多尝试三次。CI 始终上传报告并保存 30 天。

本轮退役未接入现用服务的 `video_intel.ui` 旧 Gradio 模块并移除其依赖；React 和 API 继续使用。Pillow 升至 13.0.0。定向更新 aiohttp、certifi、filelock、Mako、msgpack、multidict、setuptools、urllib3 及必要的兼容依赖，uv 升至校验固定的 0.13.4。模型、Torch/CUDA、Transformers、ComfyUI 提交与推理参数保持固定。新建或重新评估的模型例外最多有效 30 天，现有未到期例外沿用原复查日期；API、前端和工具不增加豁免。

`--upgrade-package` 可重复，不能与 `--check` 或 `--upgrade` 同用。依赖输入及 full/CI 锁一起生成和检查；禁止直接改锁绕过冲突。本轮无数据迁移或历史文件重写，不需要额外升级备份。恢复服务及真实生成验收遵循上文维护流程。
