# systemd 部署（【审计B2】部署监管）

API 与实时媒体桥（AudioSocket）全部纳入 systemd：崩溃自动拉起（Restart=always, RestartSec=3），
部署统一走 `deploy/deploy.sh`（原子重启 + 冒烟测试，任一步失败退出码 1）。

## 前提

- 代码位于 `/opt/ai_acq`（路径不同请同步修改两个 .service 文件里的 `WorkingDirectory` / `ExecStart`）
- Python 虚拟环境位于 `/opt/ai_acq/backend/.venv`
- `/opt/ai_acq/backend/.env` 已按 `.env.example` 配置

## 安装步骤

```bash
# 1. 复制 service 文件
sudo cp /opt/ai_acq/deploy/systemd/ai-acq-api.service /etc/systemd/system/
sudo cp /opt/ai_acq/deploy/systemd/ai-acq-bridge.service /etc/systemd/system/

# 2. 重载并开机自启 + 立即启动
sudo systemctl daemon-reload
sudo systemctl enable --now ai-acq-api.service ai-acq-bridge.service

# 3. 确认状态
systemctl status ai-acq-api.service ai-acq-bridge.service
```

## 日常部署

```bash
sudo bash /opt/ai_acq/deploy/deploy.sh
```

deploy.sh 流程：`git pull` → `pip install` → `systemctl restart` 两个服务 → 冒烟测试
（AudioSocket 9019 端口探测、`GET /api/health`、AMI 登录、`pjsip show contacts`）。
任一步失败立即 `exit 1`，此时不要继续放量拨打，先看日志。

## 查看日志

```bash
journalctl -u ai-acq-api.service -f
journalctl -u ai-acq-bridge.service -f
```

## 常见问题

- 冒烟报 AudioSocket 9019 探测失败：bridge 未起来或崩溃循环，`journalctl -u ai-acq-bridge -n 100` 看栈。
- 冒烟报 pjsip contacts 无注册：语音网关侧掉注册，需在网关侧重新发起 SIP 注册（见审计B1，服务器端无法代替）。
- 修改 .service 文件后必须 `sudo systemctl daemon-reload` 再 restart。
