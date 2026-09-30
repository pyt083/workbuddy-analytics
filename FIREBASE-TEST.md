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

## C. 本次未覆盖 / 已知限制

- **未在 CI 中自动跑 Emulator**：仓库未提交 GitHub Actions 工作流；`qa/` 下两个 QA 脚本可直接套进 CI。
- **密码找回、邮箱验证、第三方登录**：本次需求未要求，未实现。