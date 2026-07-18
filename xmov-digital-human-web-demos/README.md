# XMOV Digital Human Web Demos

一个基于魔珐星云 / XMOV Lite SDK 的 Web 端数字人演示合集。项目包含留学申请顾问、景区智能导览、居家养老陪伴、儿童科普实验、电商导购、企业前台、心理减压陪聊、求职面试教练、法律普法咨询、博物馆策展讲述人等多个页面。

本仓库只保留前端演示代码、静态素材和本地开发服务器。真实 API Key、App Secret、录屏文件、调试截图和历史输出均不应提交到仓库。

## 功能概览

- 本地启动一个静态 Web 服务，默认地址为 `http://127.0.0.1:4173`
- 从本地 `.env` 读取 XMOV / 魔珐星云 SDK 配置
- 页面加载 XMOV Lite SDK，并在点击“接入顾问”后初始化实时数字人
- 支持数字人语音讲解、字幕显示、场景按钮切换讲解词
- 提供 10 个独立 Web Demo 页面，适合网页演示、路演展示和短视频录制

## 目录结构

```text
.
├── public/
│   ├── index.html                 # 留学申请顾问数字人
│   ├── app.js                     # 留学申请顾问交互逻辑
│   ├── demos/
│   │   ├── scenic-guide.html       # 景区智能导览数字人
│   │   ├── care-companion.html     # 居家养老陪伴助手
│   │   ├── science-lab.html        # 儿童科普实验老师
│   │   ├── shopping-host.html      # 电商导购主播数字人
│   │   ├── front-desk.html         # 企业前台接待数字人
│   │   ├── wellness-buddy.html     # 心理减压陪聊伙伴
│   │   ├── interview-coach.html    # 求职面试教练数字人
│   │   ├── legal-guide.html        # 法律普法咨询助手
│   │   └── museum-curator.html     # 博物馆策展讲述人
│   ├── shared/
│   │   └── xmov-client.js          # 多页面共用的数字人连接与播报逻辑
│   └── assets/                     # 数字人占位图等静态素材
├── scripts/                        # 截图、录制、辅助脚本
├── server.mjs                      # 本地开发服务器与配置注入
├── .env.example                    # 环境变量模板，不含真实密钥
└── package.json
```

## 环境要求

- Node.js 18 或更高版本
- 可访问魔珐星云 / XMOV Lite SDK CDN
- 已开通的 XMOV / 魔珐星云应用配置

## 快速开始

1. 安装依赖：

```bash
npm install
```

2. 创建本地环境变量文件：

```bash
cp .env.example .env
```

Windows PowerShell 可使用：

```powershell
Copy-Item .env.example .env
```

3. 编辑 `.env`，填入自己的配置：

```env
XMOV_APP_ID=your_app_id_here
XMOV_APP_SECRET=your_app_secret_here
XMOV_SESSION_GATEWAY_URL=https://your-session-gateway.example.com
XMOV_AUTH_HEADER=
PORT=4173
```

4. 启动本地服务：

```bash
npm start
```

5. 打开浏览器访问：

```text
http://127.0.0.1:4173
```

## Demo 页面入口

- 留学申请顾问数字人：`http://127.0.0.1:4173/`
- 景区智能导览数字人：`http://127.0.0.1:4173/demos/scenic-guide.html`
- 居家养老陪伴助手：`http://127.0.0.1:4173/demos/care-companion.html`
- 儿童科普实验老师：`http://127.0.0.1:4173/demos/science-lab.html`
- 电商导购主播数字人：`http://127.0.0.1:4173/demos/shopping-host.html`
- 企业前台接待数字人：`http://127.0.0.1:4173/demos/front-desk.html`
- 心理减压陪聊伙伴：`http://127.0.0.1:4173/demos/wellness-buddy.html`
- 求职面试教练数字人：`http://127.0.0.1:4173/demos/interview-coach.html`
- 法律普法咨询助手：`http://127.0.0.1:4173/demos/legal-guide.html`
- 博物馆策展讲述人：`http://127.0.0.1:4173/demos/museum-curator.html`

## 使用方式

1. 进入任一 Demo 页面。
2. 点击“接入顾问”，等待数字人模型加载完成。
3. 数字人出现后，点击页面中的业务按钮或场景卡片。
4. 页面会切换对应内容，数字人会同步播报讲解词。

如果只看到占位图，没有出现真实数字人，通常是以下原因：

- `.env` 中的 `XMOV_APP_ID`、`XMOV_APP_SECRET` 或 `XMOV_SESSION_GATEWAY_URL` 配置错误
- 当前网络无法访问 SDK CDN 或会话网关
- 浏览器阻止了自动播放音频，需要先与页面交互
- SDK 服务端会话创建失败，可打开浏览器控制台查看错误

## 配置说明

| 变量名 | 必填 | 说明 |
| --- | --- | --- |
| `XMOV_APP_ID` | 是 | XMOV / 魔珐星云应用 ID |
| `XMOV_APP_SECRET` | 是 | XMOV / 魔珐星云应用 Secret |
| `XMOV_SESSION_GATEWAY_URL` | 是 | 会话网关地址 |
| `XMOV_AUTH_HEADER` | 否 | 可选鉴权头，只有 SDK 集成明确要求时才填写 |
| `PORT` | 否 | 本地服务端口，默认 `4173` |

## 安全说明

- 不要提交 `.env`、真实 API Key、App Secret、token、账号密码或录制产物。
- 本项目是本地演示工程，`server.mjs` 会把 SDK 初始化所需配置注入到前端。请只在可信本地环境或受控演示环境使用。
- 如果要部署到公网，请先根据魔珐星云官方安全建议改造为后端签名或临时会话方案，不要把长期有效密钥暴露给公开网页。

## 截图与录制脚本

`scripts/` 目录包含历史开发阶段使用的截图和录制辅助脚本。它们不是运行 Demo 的必要条件。开源使用时可以只关注：

- `npm start`：启动本地服务
- 浏览器访问对应 Demo 页面

如需使用 Playwright 脚本，请先确保本机已安装浏览器依赖：

```bash
npx playwright install chromium
```

## 开源打包建议

发布 zip 或提交仓库时建议只包含：

- `public/`
- `scripts/`
- `server.mjs`
- `package.json`
- `package-lock.json`
- `.env.example`
- `.gitignore`
- `README.md`

不要包含：

- `.env`
- `node_modules/`
- `output/`
- `dist/`
- 录屏文件、调试截图、真实密钥或账号信息

## License

MIT License. See `LICENSE` for details.
