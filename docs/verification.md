# 验证记录

验证日期：2026-10-26。

## 已自动验证

- 完整测试：`python -m pytest -q`。
- 导入/语法：`python -m compileall -q src streamlit_app.py`。
- 端到端模拟：网页生成 C63(C9) 的结构化载荷，GitHub broker mock 接收同一 UUID，本地 worker 调用 fake Pandat，生成 GitHub artifact，网页再按 run ID 和 job ID 下载。
- 模拟结果核对：25–1500 ℃、3 个结果点、`Fcc`/`Liquid` 相名、元数据 UUID、CSV、PNG 和内层结果 ZIP 一致。
- 工作流契约：只有 `workflow_dispatch`；固定 `Windows`、`X64`、`pandat-licensed` 标签；单作业并发；失败也上传状态 artifact；保留 7 天。
- 安全契约：网页只能提交受限 JSON；runner 再验证；没有 PBFX/命令/路径输入；token、数据库和许可证不进入 artifact。

## 本机只读检查

在没有启动 Pandat 的情况下运行 `scripts/check_local.ps1`，结果为：

```json
{"ready":false,"pandat":true,"database":true,"template":true,"runner":false}
```

这说明 Pandat 2024、商业数据库和仓库模板可读取；`ready=false` 仅因为独立 GitHub 仓库尚未创建，专用 self-hosted runner 因而尚未注册。

## 浏览器冒烟测试

本地 Streamlit 页面已在真实浏览器中检查：

- 错误访问码会被拒绝，正确访问码进入独立的 Pandat 表单；
- 默认 C63(C9) at.% 成分及 25–1500 ℃条件正确显示；
- 非递增温区在本地校验阶段阻止提交，不会调用 GitHub；
- 页面明确说明本机使用出站 HTTPS，不开放本地端口；
- 布局在当前窄视口保持单列可操作；浏览器控制台没有 error 级日志；
- 数值/成分异常、离线 runner 文案和下载绑定另由自动测试覆盖。

浏览器测试没有提交真实 GitHub 作业，也没有启动 Pandat。

## 首次真实作业清单

以下步骤需要用户账户或一次性注册令牌，当前尚未执行：

1. 在个人 GitHub 账户创建私有仓库 `pandat-cloud-bridge`，把本分支推到 `main`。
2. 授权 Streamlit Community Cloud 读取该私有仓库并创建独立应用。
3. 创建只限该仓库的 fine-grained token，并按 README 配置 Actions/Contents/Administration 权限。
4. 在仓库设置中生成一次性 runner 注册令牌，下载并注册 Windows x64 runner，增加 `pandat-licensed` 标签。
5. 在本机设置 Pandat、数据库、模板和 runner 路径，重新运行只读检查，预期五项均为 `true`。
6. 启动 runner，把 token 和访问码哈希写入 Streamlit secrets。
7. 从网页提交一个 C63(C9) 25–1500 ℃真实作业，核对 native result、CSV、PNG/PDF、metadata 和 Pandat 日志。

首次真实作业通过前，本项目的证据边界是“软件链路与 fake Pandat 已验证，本机依赖已发现”；不能声称云端到商业 Pandat 的授权计算已经完成。
