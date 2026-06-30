# 客户端内置个人号登录

平台私信系统的个人号登录需要运行在桌面客户端中。普通浏览器预览页不能把美团、饿了么、抖音等第三方登录页稳定嵌入到页面内，原因是平台通常会通过 `X-Frame-Options`、`Content-Security-Policy` 和同源策略阻止 iframe 嵌入与跨域 Cookie 读取。

当前实现使用 Electron 桌面壳在“客户端内置个人号登录工作台”的中间区域创建真实 `webview`：

- 每个私信账号使用独立 `persist:dm-<profileKey>` 分区，登录态互不串号。
- 用户在客户端内置区域完成真实平台登录。
- 点击“登录后检测”时，客户端只检测 Cookie / localStorage / 页面登录标识是否存在。
- 检测接口只接收布尔结果、当前 URL 和标题，不上传 Cookie、验证码、密码或其他敏感值。
- 检测成功后，后端才把账号标记为 `已登录` 和 `可用`。

## 本地运行

先启动后端服务，再运行前端桌面客户端：

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8017
```

```bash
cd frontend
npm run build
npm run desktop
```

开发时也可以连接 Vite 预览：

```bash
cd frontend
npm run build
npm run preview -- --port 4178
AI_ACQ_FRONTEND_URL=http://127.0.0.1:4178 npm run desktop
```

## 浏览器预览行为

`http://127.0.0.1:4178/` 仍然可以用于查看 UI 和普通业务页面，但个人号登录工作台会提示“请使用桌面客户端”。这是预期行为，不是登录功能缺失。
