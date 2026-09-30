# QA 独立验证报告 v2 —— 登录注册 + 管理员后台（Firebase）

- **QA**：严过关（software-qa-engineer-2，独立于实现工程师的自查）
- **被测对象**：`/Users/donson/WorkBuddy/2026-09-29-23-19-56/workbuddy-analytics/`（index.html 2030 行、firestore.rules、functions/index.js、firebase.json、FIREBASE-SETUP.md 等）
- **验证日期**：2026-09-30
- **验证方式**：静态审查（git diff 对比 v1.0 基线）+ **真实 Firebase Emulator Suite 端到端**（不使用工程师的 mock）+ `@firebase/rules-unit-testing` 规则单测
- **测试产物**：`qa/e2e-real-emulator.py`（41 项断言）、`qa/firestore-rules.test.js`（13 项断言），均独立于 `tests/`

---

## 0. 结论速览

| 维度 | 结果 |
| --- | --- |
| 原有 10 页业务代码无回退 | ✅ PASS（git diff 证据，见 §2.1） |
| Firestore 安全规则 | ✅ PASS（13/13 规则单测，含"前端直建 users 文档被拒"关键项） |
| 前端登录/管理后台逻辑（真实 Emulator） | ✅ PASS（41/41，**前提是先修复 P0-1**） |
| Cloud Functions 交付代码 | ❌ **P0-1：模块加载即崩溃，交付态不可部署** |
| 是否可推 GitHub Pages（静态部分） | ✅ 可以（见 §6 注意事项） |
| 是否可在真实 Firebase 启用后端 | ❌ **必须先修复 P0-1**，否则注册后永远停在「未找到用户档案」 |

---

## 1. 测试环境

| 组件 | 版本/端口 |
| --- | --- |
| firebase-tools CLI | 15.32.0 |
| Firestore Emulator | v1.22.0（localhost:8080） |
| Auth Emulator | 内置于 CLI（localhost:9099） |
| Functions Emulator | localhost:5001，hub 4400，UI 4000 |
| Emulator 项目 ID | `demo-wbqa`（demo- 前缀，离线安全模式） |
| Node | v22.22.2（firebase.json 声明 nodejs20，模拟器以宿主 22 运行，仅告警不影响） |
| Java | Temurin 24（Firestore Emulator 依赖） |
| Playwright | 1.61.0 + Chromium 1228（无头） |
| 页面载入方式 | `python3 -m http.server 8000` → `http://localhost:8000/index.html?emulator=1`（与 FIREBASE-TEST.md §B 一致） |

沙箱说明：QA 在 `/tmp/wbqa-sandbox` 复制了被测代码，仅做两处与用户等价的操作：
1. 按 FIREBASE-SETUP.md §3 把 `YOUR_*` 占位符替换为 demo 项目值（每个真实用户都必须做这步）；
2. 添加 `.firebaserc`（`firebase use --add` 的产物）。
**交付仓库本体未被 QA 修改**（`functions/index.js` 的 P0 修复仅在沙箱验证过可行性，见 §4）。

---

## 2. 静态审查结果

### 2.1 原 10 页业务代码零改动 ✅

`git diff HEAD -- index.html`（基线 8367bba，v1.0，1670 行 → 现值 2030 行，+365/-5）：

- **删除的 5 行**全部是注册/管理员改造的必要重命名：`savedReports` 行尾加逗号、`report:['reportChart']` 行尾加逗号、`PAGES` 数组追加 `'admin'`、`function init(){` → `function initDashboard(){`、`window.addEventListener('load',init)` → 新引导逻辑。
- 所有业务函数（`renderOverview/renderOrgTree/renderUsers/renderTasks/renderCategory/renderPosition/renderPrompt/renderDialogue/renderUpload/renderSavedReports/saveReport/exportCSV/exportUsers` 等）**无一改动**，仅新增 `renderUserMenu/renderAdmin` 及 `renderPage` 增加 `admin` 分支、`PAGE_CHARTS` 增加 `admin:[]`。
- CSS/HTML 全部为新增块（登录视图、用户菜单、管理后台表格），无删改。
- 业务事件绑定从 `load` 移到登录成功后的 `initDashboard()`（幂等保护 `dashboardInited`），逻辑正确。

### 2.2 firestore.rules ✅（静态 + 单测双重确认）

- 默认拒绝：`match /{document=**} { allow read, write: if false; }` 兜底。
- `users/{userId}`：`create: false`（仅 Cloud Functions 可建）、`delete: false`、`update` 用 `diff().affectedKeys().hasOnly()` 做字段级白名单（自己只能改 displayName/lastLoginAt；admin 只能改 role/status/displayName/lastLoginAt）。
- `isAdmin()` 通过 `get(users/$(uid))` 实时读取角色，无法靠客户端伪造。
- 任务要求的 4 个关键场景 + 9 个补充场景全部由规则单测证实（§3.2）。

### 2.3 functions/index.js ❌ P0-1（详见 §4）

- `setUserRole` callable 逻辑本身正确（auth 检查、admin 检查、参数校验、防自我降级、目标存在性检查），实测全部通过。
- `onAuthCreate` 首用户判断用 `count().get()`（等价于 size==0，且更省读），逻辑正确。
- **但模块第 24 行 `require('firebase-functions/v2/auth')` 在 firebase-functions@5.x 中不存在 → 整个模块加载失败**。

### 2.4 FIREBASE-SETUP.md 可执行性

总体闭环（Blaze 提醒、Email/Password 启用、Web config 填写位置、`firebase login/use --add`、functions npm install、deploy 命令、授权域名、故障排查表齐全）。两处小瑕疵：

- P3-a：§4 说「把 firebase.json 顶部的 projectId 字段改成你的项目 ID」——firebase.json 里**没有** projectId 字段，实际起作用的是 `firebase use --add` 生成的 `.firebaserc`（QA 沙箱正是这样做的）。建议删掉这句避免误导。
- P3-b：未提示 `firebase deploy` 后首次验证建议先看 Functions 控制台确认两个函数部署成功（与 P0-1 相关，修复前部署会直接报错，反而是好事——错误能被看见）。

---

## 3. 端到端实测（真实 Firebase Emulator，零 mock）

### 3.1 关键前置发现（复现过程）

在**未打任何 QA 补丁的原始交付代码**上：

```
i  functions: Watching "/private/tmp/wbqa-sandbox/functions" for Cloud Functions...
Error [ERR_PACKAGE_PATH_NOT_EXPORTED]: Package subpath './v2/auth' is not defined by "exports"
  in .../functions/node_modules/firebase-functions/package.json
⬢  functions: Failed to load function definition from source: FirebaseError:
  Functions codebase could not be analyzed successfully. It may have a syntax or runtime error.
```

此时注册用户：Auth 模拟器建号成功，但 `users/{uid}` 永远不出现，前端轮询 6 秒后显示
`未找到用户档案（请确认 Cloud Functions onAuthCreate 已部署）`（错误提示与 FIREBASE-SETUP.md §7 排查表一致，前端容错合格，但功能不通）。

为继续验证其余链路，QA 在**沙箱副本**中把触发器改为 v1 API（`require('firebase-functions/v1/auth').user().onCreate(...)`，handler 参数从 `event.data` 改为直接接收 `user`，业务逻辑零改动），模块随即加载成功，`onAuthCreate`/`setUserRole` 均正常工作。**以下 41 项结果均为打此补丁后的真实 Emulator 实测**——即：修复 P0-1 后，全链路可用。

### 3.2 用例矩阵（41 项断言 + 13 项规则断言，全 PASS）

| 用例 | 断言 | 结果 | 证据（实测输出摘录） |
| --- | --- | --- | --- |
| **A 未登录态** | A1 登录卡片可见 / A2 `.app` 隐藏 / A3 用户菜单隐藏 / A4 管理导航隐藏 / A5 仪表盘未初始化 | 5/5 PASS | `stat-cards=0`（未登录不渲染任何业务数据） |
| **B 首注册用户** | B1–B5：自动登录、`wbUser.role=admin`、管理导航可见、角色标签「管理员」 | 5/5 PASS | `wbUser.role=admin`；`alice_uid=Dsvh56gR...`（count==0 判定生效） |
| **C 第二用户** | C1–C4：`role=user`、无管理入口、标签「普通用户」；C5 强行 `switchPage('admin')` → 「⚠ 无权限」 | 5/5 PASS | `wbUser.role=user` |
| **E 非 admin 调 callable** | Bob 调 `setUserRole(uid2,'admin')` | PASS | `code=functions/permission-denied` |
| **F admin 提权** | Alice 调 `setUserRole(bob,'admin')`；Firestore 中 Bob role 确认 | 3/3 PASS | `{'ok': True, 'uid': 'PwYY...', 'role': 'admin'}` |
| **H 防锁死** | Alice 调 `setUserRole(self,'user')` | 2/2 PASS | `code=functions/failed-precondition, msg='不能被降级自己（防锁死）'`；Alice 仍 admin |
| **I 实时禁用踢出** | Alice 写 Bob `status='disabled'` → Bob（另一浏览器上下文，已登录）被 onSnapshot 踢出 | 5/5 PASS | `msg="您的账号已被管理员禁用"`，`.app` 隐藏 |
| **J 禁用后重登** | Bob 再登录 | 2/2 PASS | `err="您的账号已被禁用"`，无法绕过（登录成功后 handleAuth 检查 status 即登出） |
| **L 原业务回归** | org/users/report 三页渲染、组织树 6 节点、用户表 15 行、CSV 导出、保存报表 | 9/9 PASS | `file=用户明细.csv`；`savedReports 0 → 1` |
| **M 注册校验** | 非法邮箱 / 密码<8 / 空名称 / 重复邮箱 / 失败后不误登录 | 5/5 PASS | `邮箱格式不正确` / `密码至少 8 位` / `请填写显示名称` / `该邮箱已注册，请直接登录` |
| **规则单测 R1–R10** | 改自己 role/status→deny；读他人 doc→deny；读自己→allow；admin 写 role/status→allow；**登录/未登录直接 create users 文档→deny（关键）**；未登录读→deny；改自己 displayName→allow；admin 改 email→deny；admin delete→deny；未定义集合→deny | 13/13 PASS | 规则求值日志 `false for 'create' @ L26` 等 |

总计：**E2E 41/41 PASS，规则单测 13/13 PASS，PAGE ERRORS: []**（完整原始输出见 §7 附录说明）。

---

## 4. 问题清单（按优先级）

### 🔴 P0-1（必须修复，阻塞真实后端启用）：functions/index.js 引用不存在的模块路径

- **位置**：`functions/index.js:24`
- **现状**：`exports.onAuthCreate = require('firebase-functions/v2/auth').onAuthCreate(async (event) => {...})`
- **问题**：firebase-functions@5.x 的 package.json `exports` 中**没有 `./v2/auth` 子路径**（Auth 用户触发器只有 v1 API）。`functions/package.json` 锁的是 `^5.0.1`（实测安装 5.1.1）。模块在 `require` 阶段即抛 `ERR_PACKAGE_PATH_NOT_EXPORTED`，导致：
  - `firebase deploy --only functions` / `firebase emulators:start` 均报「Functions codebase could not be analyzed successfully」；
  - `onAuthCreate` 与 `setUserRole` **两个函数都无法部署**；
  - 上线后所有用户注册卡死在「未找到用户档案」。
- **修复建议**（QA 已在沙箱验证可行）：
  ```js
  const { user } = require('firebase-functions/v1/auth');   // 或 require('firebase-functions/v1').auth
  exports.onAuthCreate = user().onCreate(async (user) => {
    const uid = user.uid;
    const email = user.email || '';
    const displayName = user.displayName || '';
    // ……其余逻辑不变（函数体里把 event.data.xxx 改成 user.xxx）
  });
  ```
- **为何工程师自查没发现**：`tests/firebase-mock.js` 在浏览器里**模拟**了 onAuthCreate 的语义（mock 自己实现了"首用户 admin"），真实函数从未在 Node 中被加载过。FIREBASE-TEST.md §A 声称的 PASS 只覆盖了前端逻辑，§B（Emulator 路径）标注"可选"未执行。

### 🟠 P1-1（流程问题）：自查报告的置信度声明过强

FIREBASE-TEST.md 标题写「端到端验证报告 …… 结果全部 PASS」，但 A 路径是纯 mock，B 路径未跑。建议文档明确标注「A=前端逻辑（mock 后端）；B=真实后端，未执行」，避免后续维护者误以为后端可用。（P0-1 修复后建议补跑一次真实 Emulator 全流程，QA 的 `qa/` 脚本可直接复用。）

### 🟡 P2-1（纵深防御）：Firestore 规则允许 admin 通过客户端 SDK 自降/自禁

- 规则中 `isAdmin()` 在写入**前**求值：admin 直接用客户端 SDK 写自己的 `role:'user'` 或 `status:'disabled'` 会被 **allow**（affectedKeys 合法），绕过 callable 的防锁死保护与 UI 的 disabled 按钮。
- 影响评估：仅 admin 本人可对自己造成锁死（无提权风险），属低危；但与「防锁死」设计意图不符。
- 建议：规则中 admin 分支加 `uid() != userId`，即 admin 不能写自己的 role/status（自己那行走普通用户分支，只能改 displayName）。

### 🟡 P2-2（信息卫生）：firebase.json hosting.ignore 缺项

若用户选择 `firebase deploy --only hosting`，`tests/`、`qa/`、`qa-report*.md` 会被一并发布到公网（当前 ignore 只有 FIREBASE-*.md/README.md/functions/** 等）。建议补 `tests/**`、`qa/**`、`qa-report*.md`。（走 GitHub Pages 不受影响，取决于用户的发布目录配置。）

### ⚪ P3（可选优化）

- a. `fetchUserDoc` 轮询上限 30×200ms=6s：生产环境 Functions 冷启动偶发超 6s，会导致首登失败（有清晰报错+刷新可恢复，可接受；可改为指数退避或延长至 15s）。
- b. FIREBASE-SETUP.md §4 关于 firebase.json projectId 的表述与实际机制（.firebaserc）不符，建议修正。
- c. `onAuthCreate` 里对已存在用户 `update lastLoginAt` 的分支：onAuthCreate 只在**创建账号**时触发，登录不触发，该分支实际是幂等保护（事件重放场景），无害，仅注释表述略歧义。

---

## 5. 与工程师自查（FIREBASE-TEST.md）的差异对照

| 项 | 工程师（mock） | QA（真实 Emulator） |
| --- | --- | --- |
| 未登录隔离 / 注册登录 / 角色显示 / 管理入口 | PASS | PASS（结论一致） |
| setUserRole 权限、防自我降级 | PASS（mock 实现的语义） | PASS（**真实 callable + Firestore 读取**） |
| 禁用踢出 / 重登拒绝 | PASS（`__WB_FAKE__.setUserStatus` 模拟） | PASS（**真实 onSnapshot 监听 Firestore 文档变更**） |
| Firestore 规则 | 未测（文档自述） | 13/13 单测 PASS |
| **Cloud Functions 可部署性** | **未覆盖（mock 掩盖）** | **❌ P0-1：模块加载失败** |
| 原 10 页业务回归 | PASS | PASS（抽样 3 页 + CSV + 保存报表，全绿） |

---

## 6. 发布结论

1. **静态部分（index.html 及原 10 页业务）可以推 GitHub Pages**：业务代码零回退（git diff 证据），登录前整个仪表盘隐藏且不初始化，未配置 Firebase 时表现均为预期的登录卡片/错误提示，不产生 JS 报错。静态站本身无新增风险。
2. **但必须同步在 README/发布说明里写明**：真实登录后端在 P0-1 修复前**不可用**——用户按 FIREBASE-SETUP.md 部署 Functions 会直接失败（`firebase deploy` 报错，属"响亮的失败"，不会造成半可用状态）。建议**先修 P0-1 再一起发布**，或发布时在 README 顶部加显著提示。
3. P0-1 修复后（QA 沙箱已验证该修法可行），其余 41+13 项全部通过，可视为后端功能验证完成；P1/P2 建议随后跟进，不阻塞。

---

## 7. 附录：复现与产物

- E2E 脚本：`qa/e2e-real-emulator.py`（Playwright，含模拟器数据清空前置；运行：`python qa/e2e-real-emulator.py`，需 emulators + `http.server 8000` 于 /tmp/wbqa-sandbox）
- 规则单测：`qa/firestore-rules.test.js`（`FIRESTORE_EMULATOR_HOST=127.0.0.1:8080 node qa/firestore-rules.test.js`，依赖 `@firebase/rules-unit-testing`）
- P0-1 一行复现（在 functions 目录）：`node -e "require('firebase-functions/v2/auth')"` → `ERR_PACKAGE_PATH_NOT_EXPORTED`
- 模拟器日志：`/tmp/wbqa-sandbox/firebase-debug.log`、启动控制台输出（含 Failed to load function definition 报错全文）
