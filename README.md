# Pandat Cloud Bridge

独立的 Pandat 云端计算桥。网页接收和验证合金成分，通过私有 GitHub Actions 队列把作业交给保持在线的 Windows 工作站；工作站使用本机 Pandat 2024、商业数据库和许可证完成平衡 line 计算，再把原生结果、校验数据、图和表作为 Actions artifact 回传。

这个仓库与拉伸曲线工具无关，也不会把 Pandat、数据库或许可证复制到云端。

## 数据流

```text
同事浏览器 → Streamlit Cloud → GitHub workflow_dispatch
                                    ↓
                           私有仓库 Actions 队列
                                    ↓ 出站 HTTPS
                           Windows self-hosted runner
                                    ↓
                      D:\bin\Pandat.exe job.pbfx 2
                                    ↓
                  result / PNG / PDF / CSV / JSON / ZIP
```

本机不开放公网端口。runner 主动连接 GitHub；离线时作业保持 `queued`，本机重新启动 runner 后继续领取。

## 安全前提

- 仓库必须保持为个人账户下的**私有仓库**。
- workflow 只允许 `workflow_dispatch`，不得增加 `pull_request` 或来自 fork 的执行入口。
- self-hosted runner 只注册到此仓库，并带 `pandat-licensed` 标签。
- 网页不接受 PBFX、脚本、命令或本机路径，只接受结构化成分与温压条件。
- `.streamlit/secrets.toml`、`.env`、数据库和 runner 注册令牌都在 `.gitignore` 中。
- 结果是 Pandat 平衡预测，不是实验验证、实际冷却组织或动力学模拟。

## 1. 创建私有 GitHub 仓库

推荐仓库坐标：`Xiangyue-Chen/pandat-cloud-bridge`。推送本仓库的 `main` 分支后，在仓库 Settings → Actions → Runners 添加 Windows x64 self-hosted runner，并在注册时增加自定义标签：

```powershell
config.cmd --url https://github.com/Xiangyue-Chen/pandat-cloud-bridge --token <一小时内有效的注册令牌> --labels pandat-licensed
```

注册令牌只用于首次配置，不写入仓库。第一版建议在已登录的 Windows 桌面中交互式运行 runner；确认 HASP 许可证在服务会话也可用后，再评估服务模式。

## 2. 配置本机

在启动 runner 的 PowerShell 会话中设置：

```powershell
$env:PANDAT_EXE = 'D:\bin\Pandat.exe'
$env:PANDAT_DATABASE_CATALOG = "$PWD\config\databases.json"
$env:PANDAT_TEMPLATE_PATH = "$PWD\config\line-template.pbfx"
$env:GITHUB_RUNNER_ROOT = 'C:\actions-runner-pandat'
$env:PANDAT_TIMEOUT_SECONDS = '7200'
```

只读检查，不会启动 Pandat：

```powershell
powershell -NoProfile -File scripts\check_local.ps1
```

验证后以前台方式启动已配置的 runner：

```powershell
powershell -NoProfile -File scripts\start_runner.ps1
```

关闭该 PowerShell 窗口或按 `Ctrl+C` 会让 runner 离线；不会取消已经在 GitHub 排队但尚未领取的任务。

## 3. 配置 Streamlit Cloud

为该私有仓库创建一个 fine-grained GitHub token，仅选择本仓库并授予：

- Actions：Read and write（提交 workflow、查询 run、下载 artifact）；
- Contents：Read-only（最小仓库读取权限）；
- Administration：Read-only（显示 self-hosted runner 在线/忙碌状态）。

在 Streamlit Community Cloud 为此仓库创建独立应用，入口为 `streamlit_app.py`。把 `.streamlit/secrets.example.toml` 的内容复制到 Advanced settings → Secrets 并替换 token。不要提交真实 `secrets.toml`。

Streamlit 需要被授权读取个人账户的私有仓库。应用不再设置共享访问码，授权用户从科研工作台内直接使用。Streamlit 公网地址仍可被直接访问；如需限制该地址本身，应在部署边界增加正式身份认证，而不是恢复共享访问码。

## 4. 使用流程

1. 保持本机联网并运行 `scripts/start_runner.ps1`。
2. 授权用户在科研工作台打开“科研工具 → Pandat 调用”。
3. 选择已登记的数据库及其支持元素，再填写样品名、at.%/wt.% 成分、温区、步数和压力。
4. 网页显示 runner 在线状态并提交任务。
5. 点击“刷新状态”；成功后点击“获取计算结果”并下载 ZIP。

每个任务生成独立 UUID。默认 25–1500 ℃、100 steps、1 atm；成分总和只接受 99.9–100.1，并在 runner 再验证一次。数据库必须来自 `config/databases.json`，执行前还会校验目录指纹、文件 SHA-256 与元素范围。一个许可证一次只运行一个任务，其他任务排队。

本机已核对的 21 个数据库和元素范围见 [`docs/pandat-database-catalog.md`](docs/pandat-database-catalog.md)。

## 5. 结果与错误

成功 artifact 包含：

- `native.result`：Pandat 原生结果；
- `phase-diagram.png/.pdf`；
- `phase-fractions.csv`、`phase-regions.csv`；
- `metadata.json`、`status.json`；
- `pandat.stdout.log`、`pandat.stderr.log`；
- 内层完整结果 ZIP。

许可证不可用、数据库不支持元素、原生计算失败、提前退出、结果缺失/陈旧、超时和数值守恒失败使用不同错误码，不会被统一成“计算失败”。Artifact 保留 7 天。

## 6. 撤销与停用

1. 先关闭本机 runner。
2. 在 GitHub Settings → Actions → Runners 移除该 runner。
3. 在 GitHub token 设置中撤销 fine-grained token。
4. 在 Streamlit App settings 中删除 GitHub token secret，或删除该应用。

完成以上步骤后，云端不再能投递到本机；数据库和许可证始终只在本机。

## 本地开发

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
streamlit run streamlit_app.py
```

开发机上的可重复验证结果和首次真实作业清单见
[`docs/verification.md`](docs/verification.md)。
