# Pandat Cloud Bridge 设计

## 目标

建立一个与拉伸曲线工具完全分离的 GitHub 仓库和独立网页。使用者在网页填写合金成分与温度范围，云端只负责认证、排队和展示状态；真正的 Pandat 计算必须由持有合法数据库与许可证的 Windows 本机完成，结果再回传到网页下载。

## 已知条件

- 本机安装 Pandat 2024，批处理入口为 `D:\bin\Pandat.exe <batch.pbfx> 2`。
- `D:\bin\PandatConsole.exe` 存在，但已经验证稳定可用的生产通道是上述 `Pandat.exe` silent/batch 调用。
- 本机存在指定的 `PanHEA2024_TH+MB.pdb`；数据库文件、路径和许可证不得上传云端或提交 Git。
- 已有原生 line 模板可生成 25–1500 ℃、1 atm、指定步数的升温线计算，并能从日志识别成功、许可证不可用、数据库缺元素、Pandat 失败和超时。
- 用户已要求直接采用推荐方案开发，不逐项确认实现细节。

## 方案比较

### 方案 A：GitHub Actions self-hosted runner（采用）

Streamlit Cloud 使用服务器端 GitHub 凭据触发 `workflow_dispatch`；注册在独立私有仓库上的 Windows self-hosted runner 主动通过 HTTPS 从 GitHub 领取任务，在本机生成 PBFX、调用 Pandat、校验结果并上传 Actions artifact。网页轮询运行状态并下载结果。

优点：本机无需开放端口或公网 IP；任务、日志、重试和结果留有审计记录；与现有 GitHub/Streamlit 部署流程一致。代价：本机 runner 必须保持在线，Streamlit 需要一个最小权限的 GitHub 凭据，首次需要注册 runner。

### 方案 B：独立数据库任务队列 + 自定义轮询代理

使用 Supabase 或另一个云数据库保存任务，本机 Python 服务轮询并回传结果。优点是界面和任务模型自由；代价是多一个云服务、数据库权限和清理策略，当前没有现成实例，运维面更大。

### 方案 C：Cloudflare Tunnel/端口转发直连本机 API

云端直接调用本机 FastAPI。延迟低，但需要长期暴露本机服务、处理证书与访问控制；对装有商业许可证和数据库的工作站风险更高，因此不采用。

## 总体架构

```text
同事浏览器
    │ HTTPS
    ▼
独立 Streamlit Cloud 网页
    │ GitHub REST API: workflow_dispatch / run status / artifacts
    ▼
私有 GitHub 仓库 Actions 队列
    │ 本机主动出站 HTTPS 长轮询
    ▼
Windows self-hosted runner（标签 pandat-licensed）
    │ 生成 PBFX → D:\bin\Pandat.exe job.pbfx 2
    ▼
原生 result/dat + 校验 + PNG/PDF/CSV/JSON → Actions artifact
    │
    └──────────── 网页服务器端下载并交给当前会话
```

## 网页行为

- 页面使用独立名称“Pandat 云端计算桥”，不出现拉伸曲线功能。
- 页面打开后直接显示计算表单，不设置共享访问码；授权边界由科研工作台及部署环境承担。
- 输入包括样品名、成分单位（at.%/wt.%）、元素及数值、起始/终止温度、步数和压力；默认 25–1500 ℃、100 steps、1 atm。
- 成分必须为有限非负数，总和允许在 `99.9–100.1` 内并归一化到 100；未知元素、重复元素、空成分、反向温区和越界步数均在派发前拒绝。
- 提交后显示作业 ID、排队/运行/成功/失败状态、本机 runner 在线状态和失败摘要。
- 成功后提供完整 ZIP，以及原生 DAT、PNG、PDF、相分数 CSV、相区 CSV、元数据 JSON 的下载入口。
- 当前会话只显示自己提交并保存的作业 ID；刷新后可用作业 ID 恢复查询，但不提供全仓库作业浏览。

## 云端到本机的任务协议

- 网页生成随机 UUID，并把规范化 JSON 进行 URL-safe base64 编码后作为 `workflow_dispatch` 的单一 `payload_b64` 输入。
- GitHub workflow 必须位于默认分支，只响应 `workflow_dispatch`，不响应 `pull_request`、`push` 或来自 fork 的事件。
- 工作流固定运行在 `[self-hosted, Windows, X64, pandat-licensed]`，并使用仓库级单并发组，避免一个许可证同时启动多个 Pandat 进程。
- payload 只通过环境变量交给 Python，不拼接进 PowerShell 命令；worker 对全部字段重新验证，网页验证不能替代本机验证。
- worker 为每个作业建立独立目录，成功或失败都生成 `status.json`，超时只终止该作业启动的 Pandat PID。
- Actions artifact 名为 `pandat-result-<job_id>`，保留 7 天。数据库、PBFX 模板原件、许可证信息和绝对数据库路径不进入 artifact。

## 本机 Pandat 适配

- `PANDAT_EXE`、`PANDAT_DATABASE_PATH` 和 `PANDAT_TEMPLATE_PATH` 从 runner 主机环境读取；仓库提供 `.env.example`，绝不提交真实路径或凭据。
- PBFX 由经过验证的 line 模板复制生成：只修改计算名、数据库路径、单位、元素列表、端点、步数和输出文件名。
- 启动 `Pandat.exe <job.pbfx> 2`，隐藏窗口、重定向 stdout/stderr，并设置硬超时。
- 日志分类至少包括：成功、许可证不可用、数据库不支持元素、Pandat 原生失败、提前退出、结果陈旧和超时。
- 解析 `.result` 时验证温度端点、压力、相分数和、相内成分和以及相分数加权后的总体元素守恒；失败或超容差点必须标记，不能静默平滑或删相。
- 第一版只做平衡 line 计算，不宣称动力学、凝固或析出模拟。

## 安全与权限

- 推荐仓库为个人账户下的私有仓库 `Xiangyue-Chen/pandat-cloud-bridge`。
- Streamlit secrets 中的 GitHub fine-grained token 仅授予该仓库 Actions 读写和 Contents 只读；不得写入源码或日志。
- self-hosted runner 只注册到这个私有仓库，增加自定义标签 `pandat-licensed`；仓库不得运行来自 PR/fork 的代码。
- runner 默认交互式启动，确认批处理与 HASP 许可证稳定后再考虑 Windows 服务或计划任务。
- Streamlit 公网地址可被直接访问；如需限制该地址本身，应使用正式身份认证和配额控制。

## 失败与恢复

- runner 离线时任务停留 queued，网页明确提示“本机计算代理离线”，不把它显示为 Pandat 失败。
- 许可证占用、数据库缺元素、计算超时和数值校验失败分别返回不同错误码。
- 每个作业最多自动执行一次；重算由用户显式创建新作业，避免隐式重复消耗许可证时间。
- 网页或浏览器关闭不影响已提交作业；再次输入作业 ID 可以恢复状态。

## 非目标

- 不把 Pandat、商业数据库或许可证复制到云端。
- 不让 Streamlit Cloud 直接打开本机端口或远程控制桌面。
- 不接受任意 PBFX、脚本、文件路径或命令上传。
- 不把平衡计算结果描述为实验组织、冷却动力学或材料性能验证。

## 验收标准

1. 独立仓库中的 Streamlit 页面能验证输入并通过模拟 GitHub API 提交任务。
2. worker 能从 payload 生成 PBFX，并在 fake Pandat 环境完成成功、失败、超时和缺元素测试。
3. 在本机 dry-run 中能识别现有 Pandat、数据库和模板，而不会启动计算。
4. 注册 self-hosted runner 后，线上页面提交一个 C63(C9) 作业，GitHub Actions 在本机运行并回传可下载 artifact。
5. 在线结果明确标注数据库、计算范围、平衡预测边界和校验状态。
