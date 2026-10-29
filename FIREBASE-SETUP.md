# Firebase 部署指南（一次性）

> 本文档说明如何把 WorkBuddy 数据分析平台部署到一个真实的 Firebase 项目（Auth + Firestore + Cloud Functions + Hosting）。完成后，所有人都可以匿名打开页面，用邮箱密码自助注册后登录使用；首注册用户自动成为「管理员」。

## 1. 前置条件

- 一台能联网的电脑 + 一个 Google 账号
- 项目使用了 **Cloud Functions for Firebase**，需要把项目升级到 **Blaze（按量付费）** 计划；但**永远运行在本仓库代码 + 仅 ~50 个用户的体量下完全落在免费额度内**，不会产生实际扣费
- 安装 Node.js 18+ 与 npm
- 安装 Firebase CLI：`npm i -g firebase-tools`

## 2. 创建 Firebase 项目

1. 打开 <https://console.firebase.google.com/> → **添加项目** → 任意项目名（例如 `workbuddy-analytics`）→ 关闭 Analytics（可选）。
2. 创建好后，在项目控制台左侧菜单依次启用：
   - **Authentication → Sign-in method → Email/Password → 启用**
   - **Firestore Database → 创建数据库 → 以生产模式启动 → 选择区域**（推荐 asia-east1/asia-northeast1）

3. 项目 **设置 → 常规 → 您的应用 → 添加应用 → Web**（</>）→ 命名后**注册应用**，复制 `firebaseConfig` 对象。

## 3. 把 Web 配置填入代码

打开 `index.html`，找到 head 中的：

```html
<script>
window.__WB_FIREBASE_CONFIG__={
  apiKey:"YOUR_API_KEY",
  authDomain:"YOUR_PROJECT_ID.firebaseapp.com",
  projectId:"YOUR_PROJECT_ID",
  storageBucket:"YOUR_PROJECT_ID.appspot.com",
  messagingSenderId:"YOUR_SENDER_ID",
  appId:"YOUR_APP_ID"
};
</script>
```

把六个占位字段替换成第 2 步复制的真实值**，提交到 git**。

## 4. 初始化并部署（CLI）

```bash
# 登录 Google 账号
firebase login

# 在仓库根目录关联到刚才创建的项目
firebase use --add   # 选择 workbuddy-analytics（或你取的项目 ID）
# 然后把 firebase.json 顶部的 "projectId" 字段改成你的项目 ID（也可以不写，由 CLI 选择）

# 安装 functions 依赖
cd functions && npm install && cd ..

# 部署 Firestore 规则 + Functions（首次必须）
firebase deploy --only firestore:rules,firestore:indexes,functions

# 部署 Hosting（GitHub Pages 用户可以跳过这步，本地也可单独运行）
firebase deploy --only hosting
```

> **关于 Hosting**：本仓库默认走 GitHub Pages（无需 Firebase）。如果你也想用 Firebase Hosting，部署命令会把 `index.html` 推到 `https://<project>.web.app`。`firebase.json` 已经预留了 hosting + rewrites 规则（任何路径都返回 `index.html`，方便后续接路由）。

## 5. 配置授权域名（重要）

Firebase Auth 会拒绝不在白名单里的域名发起登录。

- **Firebase Hosting**：默认域名 `<project>.web.app` 与 `<project>.firebaseapp.com` 自动在白名单里，无需配置。
- **GitHub Pages**：需要进入 **Authentication → Settings → Authorized domains → Add domain**，添加 `pyt083.github.io`（或你自己的 Pages 域名）。

## 6. 端到端验证

打开部署后的 URL 或 GitHub Pages URL，预期流程：

1. 默认看到登录注册卡片
2. 点击「注册」→ 输入 显示名/邮箱/密码（≥8 位）→ 「注册并登录」
3. 由于没有任何用户，**首注册用户自动成为「管理员」**（由 Cloud Function `onAuthCreate` bootstrap）
4. 看到原 10 个页面 + 用户菜单（角色显示「管理员」）
5. 注销后用第二个邮箱注册 → **普通用户**（`role==='user'`）
6. 普通用户看不到「管理后台」入口，URL 直接访问 `?page=admin` 也会显示「无权限」
7. 管理员重新登录 → 进入管理后台 → 把第二个用户提升为 admin → 启用/禁用账号
8. 管理员被另一个管理员禁用后，自己刷新或下个操作触发实时监听 → 自动被踢出登录页

如果想本地联调，可以跳到 `FIREBASE-TEST.md` 用 Firebase Emulator Suite 跑同样流程，无需真实 Firebase 项目。

## 7. WorkBuddy Open API 接入（真实数据源）

看板支持「演示数据 (Mock) / 我的 WorkBuddy 数据」双数据源。接入真实数据需要部署 3 个新的 Cloud Functions（`wbOauthCallback` / `wbGetMyTasks` / `wbDisconnect`），并把 Client Secret 存入 Firebase Secret Manager。

### 7.1 录入 Client Secret（严禁写进任何仓库文件）

```bash
cd /Users/donson/WorkBuddy/2026-09-29-23-19-56/workbuddy-analytics
firebase functions:secrets:set WB_CLIENT_SECRET
# 按提示粘贴 WorkBuddy 第三方应用的 Client Secret（文档示例一律用 YOUR_CLIENT_SECRET 占位）
```

代码中只引用 Secret 变量名（`functions/index.js` 里 `defineSecret('WB_CLIENT_SECRET')`），值只存在 Firebase Secret Manager 中。

### 7.2 部署新函数与规则

```bash
cd functions && npm install && cd ..
firebase deploy --only functions,firestore:rules
# 部署输出应包含 wbOauthCallback、wbGetMyTasks、wbDisconnect、onAuthCreate、setUserRole
```

> 首次给函数挂 Secret 时，CLI 可能要求授权 Secret Manager 服务账号访问该 Secret，按提示执行输出的 gcloud 命令即可（或 `firebase functions:secrets:grantaccess WB_CLIENT_SECRET`）。

### 7.3 核对第三方应用配置

在 WorkBuddy 开放平台后台核对（用户已创建好第三方应用）：

- **Client ID**：`cb_YipjG5TEevNZFIblffrL`（已写入前端代码，可公开）
- **重定向 URI**：`https://pyt083.github.io/workbuddy-analytics/oauth/callback`
  - 必须与代码中 `WB_REDIRECT_URI`（`index.html`、`oauth/callback/index.html`、`functions/index.js` 三处）**字节级一致**
  - 该地址对应仓库静态文件 `oauth/callback/index.html`（GitHub Pages 路径 `/workbuddy-analytics/oauth/callback`）
- **权限范围（scope）**：`user.profile.readable user.task.readable`

### 7.4 填写回调页 Firebase 配置

`oauth/callback/index.html` head 中同样有 `window.__WB_FIREBASE_CONFIG__` 占位块，**填入与 `index.html` 相同的六项配置**（回调页需要以当前登录用户身份调用 callable）。

### 7.5 线上验证流程

1. 打开看板 → 登录 → 顶栏点「我的 WorkBuddy 数据」→ 总览页出现引导卡片 → 点「去授权」
2. 跳到 WorkBuddy 授权页 → 确认授权 → 自动回跳 `/workbuddy-analytics/oauth/callback` → 显示「授权成功」
3. 自动回到看板并加载真实任务数据（顶栏数据源高亮「我的 WorkBuddy 数据」）
4. 时间筛选 / 分类分析 / 趋势图对真实数据同样生效；「对话轮次 / 产物 / 上传资料」显示为 0 并有「API 暂未开放」标注
5. 断开授权：总览页引导卡片 →「断开授权」→ 服务端删除 token 文档，回退 Mock

详细验证清单见 `FIREBASE-TEST.md`「D. 真实 Open API 线上验证清单」。

### 7.6 Token 安全模型（速查）

- access_token / refresh_token **全程只在 Cloud Functions 服务端**：交换、刷新、存储均不经过浏览器
- token 存 Firestore `/wb_tokens/{open_id}`（含关联的 firebase uid），`firestore.rules` 对该集合**客户端完全 deny**
- 浏览器只拿到 `open_id` + 昵称等非敏感信息
- access_token 1 小时有效；`wbGetMyTasks` 会在过期前 60 秒自动用 refresh_token 刷新并回写
- refresh 也失败（用户在 WorkBuddy 侧撤销授权）→ callable 返回 `failed-precondition` → 前端引导重新授权

## 8. 故障排查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 登录页一直停在「Firebase SDK 加载失败」 | CDN 被墙 | 把 4 个 Firebase compat JS 下载到同目录并把 `<script src>` 改为相对路径 |
| 注册后无限 loading，找不到用户档案 | `onAuthCreate` 没部署/没运行 | `firebase deploy --only functions`；Emulator 模式下面要 `firebase emulators:start --only auth,firestore,functions` |
| 普通用户看到管理后台 | Firestore 规则没部署 | `firebase deploy --only firestore:rules` |
| 管理员被禁用没被踢出 | Firestore 实时监听未启用 | 浏览器控制台应能看到 `userDocSnapshot err` 警告；通常因为 Firestore 区域与 SDK 不匹配 |
| GitHub Pages 上登录返回 `auth/unauthorized-domain` | 域名未加白名单 | 见 §5 |
| 点「去授权」跳转后 WorkBuddy 报 redirect_uri 不匹配 | 回调地址与登记不一致 | 三处 `WB_REDIRECT_URI` 必须与开放平台后台登记的完全一致（见 §7.3） |
| 回调页报 `state 校验失败` | 发起授权与回调不在同一浏览器会话 | 回到看板重新点「去授权」（state 存 sessionStorage，正常流程不会触发） |
| 拉数据报 `functions/external` | WorkBuddy 接口不可达 / Client Secret 错误 | `firebase functions:secrets:set WB_CLIENT_SECRET` 重录；检查函数日志 `firebase functions:log` |
| 拉数据报 `failed-precondition` | 未授权 / 用户撤销授权 / refresh 失败 | 正常引导：重新点「去授权」 |
| 回调页报「请先登录看板账号」 | 回调时 Firebase 会话不存在 | 先回看板登录，再重新发起授权 |