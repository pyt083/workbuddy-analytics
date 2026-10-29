# 登录 / 管理后台 端到端验证报告

> 记录对「邮箱密码登录 + 首用户管理员 + 管理后台」功能的验证步骤、命令与实测结果。
>
> **两条独立验证路径，互不替代**：
>
> | 路径 | 介质 | 范围 | 适用场景 | 是否已实测 |
> | --- | --- | --- | --- | --- |
> | **B. 真实 Firebase Emulator Suite（推荐）** | 真实 Auth/Firestore/Functions + 真实 `firestore.rules` | 41 个端到端用例 + 13 个规则单测，覆盖规则拒绝、callable、防锁死、实时踢出等全部行为 | 改规则/改函数后必跑；交付前主验证 |
> | **A. 无头浏览器 + Firebase Mock（快速烟测）** | in-memory 替换 `window.firebase`，**不**校验 Firestore 规则、**不**走真实函数部署 | 前端逻辑主路径（登录/注册/管理员渲染/CSV 导出） | CI 烟测、离线快速验证 |
>
> **结论**：B 路径已被 `software-qa-engineer-2` 独立执行 41/41 PASS，A 路径在本仓自测中 11/11 PASS。本文档以前者为准进行描述，A 作为快速自测方案附在末尾。

---

## B. 真实 Firebase Emulator Suite（推荐，已实测 41 例 PASS）

### B.1 准备

```bash
# 1) 安装 firebase CLI（一次）
npm i -g firebase-tools

# 2) 启动模拟器（无需 firebase login，使用 demo 项目 ID 即可）
cd /Users/donson/WorkBuddy/2026-09-29-23-19-56/workbuddy-analytics
firebase emulators:start --only auth,firestore,functions --project demo-wb
#   看到 "All emulators ready!" 后，UI 在 http://localhost:4000
#   真实函数会执行 onAuthCreate / setUserRole，规则会被强制校验

# 3) 另开终端启动静态服务
python3 -m http.server 8000
```

### B.2 浏览器手动核对

打开 **<http://localhost:8000/?emulator=1>**（`?emulator=1` 让页面连接 9099/8080/5001 三个本地端口），按以下 7 步人工核对：

1. 只看到登录卡片，底部提示「已连接到 Firebase 本地模拟器」；
2. 注册 `alice@demo.com` → Emulator UI → Authentication 出现该用户，Firestore `users/{uid}` 出现文档且 `role='admin'`；
3. 管理后台仅 Alice 一行，自己的「禁用」按钮 disabled；
4. 注销 → 注册 `bob@demo.com` → `role='user'`，无管理后台入口；
5. Alice 登录 → 提升 Bob 为 admin；
6. 用 Bob 登录 → 在管理后台禁用 Alice → Alice 会话被实时监听踢出；
7. Emulator UI → Authentication 中 Alice 显示 Disabled，重登报 `auth/user-disabled`。

### B.3 自动化端到端（41 例，QA 实测 PASS）

QA 在 `qa/e2e-real-emulator.py`（与本仓 `tests/` 完全独立）执行了 41 个端到端断言，全部通过。脚本要点：

- 不使用任何 mock，直接连本地 Auth(9099)/Firestore(8080)/Functions(5001)；
- 通过 Emulator REST 接口在测试前清空 Auth 与 Firestore 数据，保证「首注册用户=admin」用例成立；
- 页面 URL 带 `?emulator=1`；
- 覆盖：注册首位→admin / 第二位→user / 非 admin 无权限 / callable 拒绝 / 提权 / 自我降级被阻止 / 实时禁用踢出 / 重登被拒 / 原 10 页功能保留 / CSV 导出 / …

运行方法见脚本头部注释。

### B.4 自动化规则单测（13 例，QA 实测 PASS）

QA 在 `qa/firestore-rules.test.js` 用 `@firebase/rules-unit-testing` 跑 13 个规则断言（亦全部通过），覆盖：

- 未登录 → 拒绝所有读；
- 普通用户 → 仅能读自己 doc；
- 普通用户 → 拒绝写 role/status；
- 管理员 → 可读所有 user doc；
- 管理员 → 可改他人 role/status；
- 管理员 → 拒绝改自己的 role/status（纵深防御）；
- 非管理员 → 拒绝调用 `setUserRole` callable；
- 其它集合 → 全部 deny。

运行方法：`node qa/firestore-rules.test.js`（需 Firestore emulator 已在 8080 端口运行）。

### B.5 覆盖矩阵

| 需求 | 验证手段 | 结果 |
| --- | --- | --- |
| 未登录只能看到登录页 | B.3 端到端 | PASS |
| 邮箱密码注册/登录 | B.3 端到端 | PASS |
| 密码强度（≥8 位） | 前端 `doSignUp` 校验 + 真实 Auth 弱密码策略 | PASS |
| 记住会话 | 真实 Auth 本地持久化 + `onAuthStateChanged` | PASS |
| 用户档案六字段 | B.3 端到端 + Firestore Emulator UI 核对 | PASS |
| 首注册用户自动管理员 | B.3 端到端 + 函数日志 `onAuthCreate` | PASS |
| 管理后台仅管理员可见 | B.3 端到端 + B.4 规则单测 | PASS |
| 改角色、启停账号、显示最后登录时间 | B.3 端到端 | PASS |
| 禁止管理员降级自己（防锁死） | B.3 端到端 + B.4 规则单测 | PASS |
| 管理员被禁用后立即退出 | B.3 端到端 + 实时 `onSnapshot` | PASS |
| Firestore 安全规则完备 | B.4 规则单测（13 例） | PASS |
| 原 10 页功能不回退 | B.3 端到端（含 10 页遍历 + CSV 导出） | PASS |

---

## A. 无头浏览器 + Firebase Mock（快速自测，可选）

### 为什么用 Mock

`index.html` 里加载的 Firebase 是按需 CDN 引入；为了让自动化测试**零依赖、离线可跑、可复现**，仓库在 `tests/` 目录提供：

- `tests/firebase-mock.js` —— 用 `page.add_init_script` 在页面脚本之前注入，替换 `window.firebase`，
  实现 Auth / Firestore / Functions 三个 compat API 所需子集（含 `onAuthStateChanged`、`createUserWithEmailAndPassword`、
  `signInWithEmailAndPassword`、`signOut`、`collection().doc().get/set/update/onSnapshot`、`collection().get/orderBy`、`httpsCallable('setUserRole')`），
  并在注册时模拟 Cloud Functions `onAuthCreate` 的 bootstrap 语义（首个用户 → `role='admin'`，其后 → `role='user'`）。
  同时暴露 `window.__WB_FAKE__.setUserStatus(uid, status)` 用于模拟「另一端管理员把当前用户禁用」的实时事件。
- `tests/e2e-auth-admin.py` —— Playwright 驱动，在网络层拦截并 abort 所有 `*.gstatic.com` 请求（避免真实 SDK 覆盖 mock，jsdelivr 的 ECharts 正常放行），然后逐条断言。

> ⚠️ Mock 路径**不**会校验 `firestore.rules`，**不**走真实 Cloud Functions 部署，**不**触发真实 Auth 弱密码策略——它只覆盖前端主路径的逻辑分支。改规则/改函数后请改走 B 路径。

### 运行命令

```bash
# 依赖：pip install playwright && playwright install chromium
cd /Users/donson/WorkBuddy/2026-09-29-23-19-56/workbuddy-analytics
python3 tests/e2e-auth-admin.py
```

### 实测输出（节选，全部 PASS）

```
=== 1) 未登录态 ===
  [PASS] login view visible      # 登录卡片可见
  [PASS] app hidden              # 原 10 页容器 .app 隐藏
  [PASS] user menu hidden
  [PASS] admin nav hidden
=== 2) 注册首位用户 Alice（自动管理员）===
  [PASS] alice user doc exists   # Cloud Functions onAuthCreate 语义已触发
  [PASS] alice role = admin      # 首注册用户 = 管理员 ✓
  [PASS] dashboard shown         # 登录后进入看板
  [PASS] user menu shown         # 右上角出现用户菜单
  [PASS] user is admin
  [PASS] admin nav visible       # 左侧出现「管理 / 管理后台」
  [PASS] admin group visible
  [PASS] overview stat cards     # 原总览页 6 张指标卡正常
=== 3) Alice 进入管理后台，列出自己一行；自我禁用按钮 disabled ===
  [PASS] admin rows = 1
  [PASS] self-action disabled    # 防锁死：禁用自己的按钮 disabled
  [PASS] no promote btn on self  # 防锁死：自己不显示「提升为管理员」
=== 4) 注销，注册第二位用户 Bob（role=user）===
  [PASS] login view after signout
  [PASS] bob user doc exists
  [PASS] bob role = user         # 第二个用户 = 普通用户 ✓
  [PASS] admin nav HIDDEN (Bob)  # 普通用户看不到管理后台入口
=== 5) Bob 强行访问 admin 页面 → 显示无权限 ===
  [PASS] admin page shows denial # 即使拿到 page id，也渲染「⚠ 无权限」
=== 6) Bob 调 setUserRole → functions/permission-denied ===
  [PASS] non-admin callable rejected: Error: 需要管理员权限
=== 7) 注销 Bob，登录 Alice，把 Bob 提升为管理员 ===
  [PASS] admin rows = 2
  [PASS] bob promoted            # callable setUserRole 生效
=== 8) Alice 试图降级自己 → blocked（防锁死）===
  [PASS] alice still admin (no self-demote)
  [PASS] mock store: alice role unchanged
=== 9) __WB_FAKE__.setUserStatus(alice,"disabled") 触发实时监听 → Alice 被踢出 ===
  [PASS] after disable, login visible
  [PASS] after disable, app hidden
  [PASS] after disable, currentUser null
=== 10) Alice 重新登录被拒绝（user-disabled）===
  [PASS] signin rejected when disabled
=== 11) 登录 Bob（现在是 admin）→ 走完原 10 页 + 导出 CSV ===
  [PASS] overview stat cards after bob login
  [PASS] 遍历 10 个原页面 + 1 个 admin 页面无报错
  [PASS] 导出 CSV: 用户明细.csv

PAGE ERRORS: []
CONSOLE ERRORS: []
OVERALL: PASS
```

---

## C. WorkBuddy Open API 接入逻辑单测（已执行，55/55 PASS）

真实 API 无法在本地测（Client Secret 仅存于 Firebase Secret Manager、生产 token 需用户在 WorkBuddy 侧亲自授权），因此**纯逻辑部分**用单元测试固化，**在线行为**列入 D 节清单由用户线上核对。

```bash
cd /Users/donson/WorkBuddy/2026-09-29-23-19-56/workbuddy-analytics
node tests/wb-oauth-mock.js
```

覆盖 55 项断言：

- **authorize URL 拼接**：`redirect_uri` 与登记地址字节级一致（原始 URL 中 `:` `/` 均被 URL 编码）、`response_type=code`、`client_id`、`scope=user.profile.readable user.task.readable`、`state` 随机值原样往返
- **回调页一致性**：`oauth/callback/index.html` 的 `WB_REDIRECT_URI` 与主页/服务端一致；state 校验、`localStorage wb_data_source=real`、跳回主页（绝对路径 `/workbuddy-analytics/`，不依赖相对层级）逻辑均在
- **wbOauthCallback 换 token 表单**：5 字段齐全（`grant_type=authorization_code` + `code` + `client_id` + `client_secret` + `redirect_uri`），`client_secret` 由调用方传入（代码不硬编码）；表单体 `application/x-www-form-urlencoded` round-trip 无损
- **refresh 分支**：`grant_type=refresh_token` + `refresh_token` + `client_id` + `client_secret` 字段正确
- **classifyTaskName**：18 个样本覆盖 7 个类别（文档写作/数据分析/PPT制作/代码开发/翻译/图片设计/视频生成）+ 默认「其他」
- **mapWbStatus**：completed/done→已完成，cancelled/failed→已取消，running/空→进行中
- **扫描逻辑自检（不含真实 secret）**：仓库测试只用**假 secret** 验证扫描器可用（造临时泄漏文件必须被检出→清理后全仓 clean）；真实 secret 的扫描见下节

实测输出尾部：`总计: 55 项，失败: 0 / OVERALL: PASS`

### C.1 真实 Client Secret 泄漏扫描（本地工具，仓库内零 secret）

仓库内**不包含**任何真实 secret 片段（2026-09-30 P1-1 修复：此前测试文件以分段字面量内置 secret，已彻底移除）。对真实 secret 的全仓扫描用 `tests/secret-scan.js`，secret 从**仓库外**读取：

```bash
# 方式一：环境变量
WB_SCAN_SECRET='YOUR_CLIENT_SECRET' node tests/secret-scan.js

# 方式二：home 目录文件（单行，勿加引号；在仓库外，已被 .gitignore 双保险排除）
echo 'YOUR_CLIENT_SECRET' > ~/wb-secret.txt
node tests/secret-scan.js
```

扫描形态（与 QA v3 同口径）：明文 / 小写 / 大写 / 反转 / base64 / base64 去填充 / 反转后 base64 / hex / hex 大写 × 完整 secret + 前后半段（部分泄漏也能检出）；范围覆盖**工作区全部文件 + git 历史所有 blob**。

最近一次实测（2026-09-30，修复 P1-1 后）：`SECRET SCAN: CLEAN (0 hits across all variants)`，工作区 23 文件 + git 3 blobs 全部干净。同口径的 `qa/secret-scan-v3.py`（已改为同样的外部读取方式）结果一致 CLEAN。

---

## D. 真实 Open API 线上验证清单（需用户执行后核对）

> 本节无法在本地自动化：Client Secret 只在 Firebase Secret Manager（`firebase functions:secrets:set WB_CLIENT_SECRET`），且授权必须由真实 WorkBuddy 账号在 `https://www.workbuddy.cn` 侧确认。部署完成后按下面顺序核对，逐项打勾。

### D.0 前置

- [ ] `firebase deploy --only functions,firestore:rules` 成功，输出包含 `wbOauthCallback` / `wbGetMyTasks` / `wbDisconnect`
- [ ] `firebase functions:secrets:set WB_CLIENT_SECRET` 已录入（值为 WorkBuddy 第三方应用的 Client Secret）
- [ ] WorkBuddy 开放平台后台：重定向 URI 为 `https://pyt083.github.io/workbuddy-analytics/oauth/callback`
- [ ] `oauth/callback/index.html` 的 `window.__WB_FIREBASE_CONFIG__` 已填（与主页同一份配置）
- [ ] Firebase Auth → Authorized domains 已含 `pyt083.github.io`

### D.1 授权流程

- [ ] 登录看板 → 顶栏点「我的 WorkBuddy 数据」→ 总览页出现引导卡片（流程说明 + 「去授权」按钮）
- [ ] 点「去授权」→ 跳转到 `https://www.workbuddy.cn/openapi/v2/authorize?...`，地址栏可见 `client_id=cb_YipjG5TEevNZFIblffrL`、`redirect_uri=https%3A%2F%2Fpyt083.github.io%2Fworkbuddy-analytics%2Foauth%2Fcallback`、`scope=user.profile.readable%20user.task.readable`、随机 `state`
- [ ] WorkBuddy 侧确认授权 → 回跳 `https://pyt083.github.io/workbuddy-analytics/oauth/callback?code=...&state=...` → 显示「授权成功，正在返回看板」
- [ ] 自动回到看板 → 顶栏数据源高亮「我的 WorkBuddy 数据」→ 总览指标卡显示真实任务数

### D.2 token 服务端持有（安全验证）

- [ ] 浏览器 DevTools → Application → Local Storage：**没有** access_token / refresh_token（只有 `wb_data_source=real`）
- [ ] Firestore 控制台：`wb_tokens/{open_id}` 文档存在（含 uid 关联、expiresAt、profile），`users/{uid}` 多了 `wbOpenId` 字段
- [ ] 浏览器控制台执行 `firebase.firestore().collection('wb_tokens').get()` → **被规则拒绝**（Permission denied）

### D.3 真实数据展示

- [ ] 任务明细页：显示真实 task_id / 标题 / 状态；「对话轮次 / 产物数」列为 0
- [ ] 任务分类分析 / 趋势图 / 时间筛选（今天/本周/本月/近90天/自定义）对真实数据生效
- [ ] 提示词 / 多轮对话 / 上传资料三页顶部出现「API 暂未开放」黄色提示条
- [ ] 组织架构页顶部出现「真实任务仅归属授权账号」提示条；用户=授权账号自己（部门「授权账号」，岗位/业务线「—」）
- [ ] 导出 CSV（任务明细）正常，包含真实任务数据

### D.4 token 刷新与失效

- [ ] 等 access_token 过 1 小时（或 Firestore 里把 `expiresAt` 改小）→ 再点一次「我的 WorkBuddy 数据」/「重新拉取任务」→ 自动刷新成功，无需重新授权
- [ ] 在 WorkBuddy 侧撤销授权（或把 `wb_tokens` 文档的 `refreshToken` 改为无效值）→ 拉取时弹「授权信息缺失或已失效」→ 总览页引导卡片重新出现

### D.5 断开与注销

- [ ] 引导卡片「断开授权」→ 确认 → 回退演示数据；Firestore `wb_tokens` 文档已删、`users/{uid}.wbOpenId` 已清
- [ ] 注销登录 → 数据源自动回退「演示数据」；重新登录后若 localStorage 偏好为 mock 则保持演示数据
- [ ] Mock 模式全流程（原 10 页 + 登录/管理员后台）与接入前完全一致（本节 + B 路径已自动化验证）

---

## E. 本次未覆盖 / 已知限制

- **未在 CI 中自动跑 Emulator**：仓库未提交 GitHub Actions 工作流；`qa/` 下两个 QA 脚本可直接套进 CI。
- **密码找回、邮箱验证、第三方登录**：本次需求未要求，未实现。
- **真实 Open API 行为**：见 D 节，需线上由用户执行核对。