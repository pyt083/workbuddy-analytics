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

## 7. 故障排查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 登录页一直停在「Firebase SDK 加载失败」 | CDN 被墙 | 把 4 个 Firebase compat JS 下载到同目录并把 `<script src>` 改为相对路径 |
| 注册后无限 loading，找不到用户档案 | `onAuthCreate` 没部署/没运行 | `firebase deploy --only functions`；Emulator 模式下面要 `firebase emulators:start --only auth,firestore,functions` |
| 普通用户看到管理后台 | Firestore 规则没部署 | `firebase deploy --only firestore:rules` |
| 管理员被禁用没被踢出 | Firestore 实时监听未启用 | 浏览器控制台应能看到 `userDocSnapshot err` 警告；通常因为 Firestore 区域与 SDK 不匹配 |
| GitHub Pages 上登录返回 `auth/unauthorized-domain` | 域名未加白名单 | 见 §5 |