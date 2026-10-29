# WorkBuddy 数据分析平台（演示版）

一个**纯静态单页 HTML 看板**，模拟 WorkBuddy 企业后台数据分析场景：约 200 名员工、5 个一级部门（各含 2–3 个二级部门）、90 天使用数据。全部 CSS/JS 内联在单个 `index.html` 中，无需构建、无外部依赖（仅图表库走 CDN），可直接托管到 GitHub Pages。

- 页面顶部平台名：**WorkBuddy 数据分析平台**
- 数据源切换：顶栏「演示数据 (Mock) ⇄ 我的 WorkBuddy 数据」双源切换（默认 Mock，见第四节）
- 图表库：ECharts 5（`https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js`）
- 主题：浅色商务风，主色 `#2563eb`，中文界面，左侧深色导航 + 顶部全局筛选栏 + 右侧内容区

## 一、页面结构（10 个页面，左侧一级导航）

**数据板块**

| 页面 | 说明 |
| --- | --- |
| 1. 总览看板 | 6 个核心指标卡（活跃用户数、任务总数、日均任务数、平均对话轮次、产物生成量、上传资料数，均带环比涨跌）；任务量+活跃用户双轴趋势图（按天/周/月切换）；任务量 Top5 部门、Top10 个人、Top5 类别三个排行榜；接入真实数据源时展示「WorkBuddy 数据接入」引导卡片（去授权 / 已连接 / 断开授权） |
| 2. 组织架构视图 | 左侧组织树（公司 → 一级部门 → 二级部门/小组 → 个人，逐级展开/折叠，默认展开一级，展开状态记忆于 localStorage）；右侧联动展示该层级汇总指标、下级成员列表（可按任务数/轮次/产物数排序）、任务类别分布饼图；顶部「按组织架构 / 按用户 / 按任务详情」三模式切换 |
| 3. 用户明细 | 表格（姓名、工号、部门、岗位、业务分类、任务数、对话轮次、产物数、上传资料数、最近活跃时间）；列排序、关键字搜索、分页；点击行展开个人详情（类别分布小图 + 时间趋势小图 + 任务列表）+ 导出 CSV |
| 4. 任务明细 | 每条任务一行（任务ID、标题、用户、部门、任务类别、岗位、业务线、对话轮次、产物数、时间、状态）；展开可看提示词全文、多轮对话记录（按轮次折叠）、产物链接占位、上传资料列表；筛选：部门/用户/任务类别/岗位/业务线 + 导出 CSV |

**数据分析板块**

| 页面 | 说明 |
| --- | --- |
| 5. 任务分类分析 | 类别占比饼图 + 数量柱状图 + 90 天趋势堆叠面积图；点击图例/柱子/扇区下钻到该类别任务明细列表（可导出 CSV） |
| 6. 岗位/业务分析 | 岗位 × 任务类别、业务线 × 任务类别两张交叉热力图 + 交叉统计表（可导出 CSV） |
| 7. 提示词与产物分析 | 提示词长度分布直方图、高频关键词 Top15 横向条形图、产物类型分布饼图 |
| 8. 多轮对话分析 | 轮次分布柱状图（1轮/2-3轮/4-6轮/7轮以上）、各部门与各岗位平均轮次对比条形图、高轮次（≥7轮）任务特征卡片 + 典型任务示例 |
| 9. 上传资料分析 | 资料类型分布饼图（PDF/Word/Excel/图片/PPT/其他）、上传频次 Top10 用户条形图、资料类型 × 任务类别热力图 |
| 10. 自定义报表 | 维度单选（时间按天/按周/按月、部门、岗位、任务类别）× 指标多选（任务数/对话轮次/产物数/上传资料数）→「生成报表」动态渲染图表 + 明细表格；「保存为常用报表」写入 localStorage，页面加载时恢复列表，支持应用/删除；可导出 CSV |

## 二、全局交互

- **全局时间筛选**（顶部）：今天 / 本周 / 本月 / 近90天 / 自定义（起止日期）。切换后所有页面的数据重新过滤聚合并刷新图表，筛选逻辑真实生效（数据按时间戳过滤，非前端假过滤）。
- **下钻联动**：分析板块图表点击元素（扇区/柱子/图例/面积系列）→ 底部联动明细表显示对应任务。
- **导出 CSV**：所有明细表格旁均有「导出 CSV」按钮，使用 `Blob` + `a.download` 真实导出**当前筛选结果**（含 UTF-8 BOM，Excel 中文不乱码）。
- **状态记忆**：组织树展开状态（`wb_org_expand`）与常用报表（`wb_saved_reports`）存于 localStorage。
- **图表自适应**：页面切换时对目标页图表 `resize()`，窗口 resize 时统一 `resize()`。

## 三、部署方式（GitHub Pages）

1. 新建仓库并把 `index.html`、`oauth/callback/index.html`（OAuth 回调页，必需）连同本 README 推到默认分支，例如 `main`：

   ```bash
   git init
   git add index.html oauth/ README.md
   git commit -m "feat: WorkBuddy 数据分析平台演示看板"
   git branch -M main
   git remote add origin https://github.com/<your-name>/<repo>.git
   git push -u origin main
   ```

2. 仓库 **Settings → Pages**：Source 选择 `Deploy from a branch`，Branch 选 `main` + `/ (root)`，保存。
3. 稍等 1 分钟，访问 `https://<your-name>.github.io/<repo>/` 即可。

> 说明：单文件内联 CSS/JS，无需构建产物；ECharts 通过 jsDelivr CDN 加载，访问环境需能连通公网 CDN（若内网受限，可把 `echarts.min.js` 下载到同目录并把 `<script src>` 改为相对路径）。

本地预览：直接用浏览器打开 `index.html`，或在目录下执行 `python3 -m http.server 8080` 后访问 `http://localhost:8080/`。

## 四、数据源：演示数据 (Mock) ⇄ 我的 WorkBuddy 数据（双源）

顶栏提供数据源切换器（默认 **Mock**，一切保持不变）：

- **演示数据 (Mock)**：内置 Mock 数据生成器（固定种子 `mulberry32(20260929)`）生成约 200 名员工、5 个一级部门、90 天使用数据，**刷新页面数据保持一致**。数据模型：
  - **用户**：工号 `WB0001` 起；中文姓名；部门 / 二级部门；岗位；业务分类（智影 / 智剪 / 智图 / 中台）。
  - **任务**：ID `T10001` 起；标题由模板池 × 变量组合；类别 8 种（文档写作/视频生成/图片设计/数据分析/代码开发/PPT制作/翻译/其他）；对话轮次 1–12；产物 0–5；上传资料 0–3；提示词；多轮对话；时间近 180 天随机；状态（已完成/进行中/已取消）。

- **我的 WorkBuddy 数据（真实 Open API）**：通过 **WorkBuddy 开放平台 OAuth2.1** 接入：
  - 顶栏点「我的 WorkBuddy 数据」→ 未授权时总览页出现引导卡片（流程说明 + 「去授权」）
  - 「去授权」跳 `https://www.workbuddy.cn/openapi/v2/authorize`（scope：`user.profile.readable user.task.readable`，随机 state 存 sessionStorage 防 CSRF）
  - 授权确认后回跳 `oauth/callback/index.html`（静态回调页）→ 调 Cloud Function `wbOauthCallback` 换 token → 回主页自动加载真实任务
  - **token 全程服务端持有**（存 Firestore `wb_tokens/{open_id}`，客户端规则完全 deny，浏览器只拿 `open_id` + 昵称）
  - **任务**映射：真实 `task_id / name / status / created_at`；任务类别由 `classifyTaskName()` 关键词规则从标题分类（8 类）；**用户**为授权账号本人（部门「授权账号」，岗位/业务线「—」）
  - **API 暂未开放维度**（对话轮次 / 产物数 / 上传资料）置 0，相关页面顶部有「API 暂未开放」黄色提示条
  - 时间筛选 / 分类分析 / 趋势图 / CSV 导出对真实数据同样生效
  - token 失效自动用 refresh_token 刷新；refresh 也失败 → 引导卡片重新授权；支持「断开授权」删除服务端凭证
  - 数据源偏好存 localStorage（`wb_data_source`），重新登录自动恢复；注销登录自动回退 Mock

架构：页面统计统一经由 `DataAdapter` 取数，`MockDataSource`（同步）与 `ApiDataSource`（异步经 callable `wbGetMyTasks`）实现同一数据模型 `{ users, tasks }`，切换时 `applyDataset()` 重建全局数据集，页面渲染与统计代码无需感知。接入部署见 [`FIREBASE-SETUP.md`](./FIREBASE-SETUP.md) 第 7 步，验证清单见 [`FIREBASE-TEST.md`](./FIREBASE-TEST.md) D 节。

## 五、登录与管理员后台（双轨鉴权：演示模式 / 云端模式）

页面在未登录时会显示一张居中的登录卡片（原 10 页全部隐藏）。登录后才能进入看板；右上角头像下拉包含「管理后台」（仅管理员可见）与「退出登录」。

### 5.0 两种模式与自动切换

看板采用**双轨鉴权**：同一套 `AuthAdapter` 接口（`authRegister / authLogin / authLogout / authGetUser / authListUsers / authSetRole / authSetStatus / onAuthChanged`），两种实现。

页面初始化时读 `index.html` 顶部 `window.__WB_FIREBASE_CONFIG__`，**仅当 `apiKey`、`projectId`、`appId` 三个字段都填了真实值（不是 `YOUR_…` 占位符）** 时才走云端模式；否则自动降级为演示模式。**未部署 Firebase 后端时，站点开箱可用——任何人都能注册、登录、使用管理后台。**

| | 演示模式（local） | 云端模式（firebase） |
| --- | --- | --- |
| 触发条件 | `apiKey`/`projectId`/`appId` 任一缺失或仍是 `YOUR_` 占位符 | 三者均为真实值 |
| 账号存储 | 浏览器 `localStorage`：`wb_local_accounts`（账号表）、`wb_local_session`（当前 uid） | Firebase Authentication + Cloud Firestore `users/{uid}` |
| 口令 | `SHA-256(salt + password)`（SubtleCrypto），16 位随机 salt，**不存明文**；非安全上下文自动降级为弱哈希并标记 `hashMode='insecure'` | 由 Firebase Authentication 托管 |
| 首注册用户 | 自动管理员（`role='admin'`），后续为普通用户 | 同左（由 Cloud Functions `onAuthCreate` bootstrap） |
| 管理后台 | 可见，直接读写本地账号表 | 可见，走 Firestore + callable `setUserRole` |
| 真实数据源 | 置灰不可用（OAuth 回调与 token 存储依赖 Cloud Functions） | 可用 |
| 账号有效期 | 仅当前浏览器，换浏览器/清缓存即丢失 | 跨设备持久 |

演示模式的可见标识：登录页黄色横幅「演示模式：账号仅保存在本浏览器…」、顶栏「演示模式」chip、用户菜单「当前模式：演示模式（本机账号）」、管理后台顶部提示条。

**云端不可用时的兜底**：若判定为云端模式但 Firebase SDK 加载失败或初始化抛错，登录页会显示红色错误卡片（说明原因 + 修复指引），并提供「改用演示模式（本地账号）」按钮一键降级——**不会白屏、不会静默失败**。

### 5.0.1 开箱即用的演示账号

演示模式下**首次加载会自动写入一个种子管理员账号**，打开站点即可登录，无需先注册：

| 项 | 值 |
| --- | --- |
| 邮箱 | `admin@workbuddy.local` |
| 密码 | `WorkBuddy@2026` |
| 角色 | 管理员（`role=admin`，可进入管理后台） |

- 登录卡片内直接展示这组凭据，并有「**一键填入并登录**」按钮；同时保留自助注册入口。
- 口令与其它本地账号一样走 **16 位随机 salt + `SHA-256(salt|password)`** 存储，浏览器中**没有明文密码**。
- 种子账号占用「第一个账号」名额，因此**之后自助注册的账号为普通用户**；
  在管理后台「清空本地演示账号」后**立刻注册**，那个账号才会成为管理员；若改为**刷新页面**，种子账号会重新生成。

> ⚠️ **请务必知悉**：演示账号只存在**当前浏览器**的 localStorage；**任何访问该网址的人都可以使用上面这组公开凭据登录**并查看演示数据（Mock）。请勿在演示模式填写任何真实信息。
> 一旦在 `index.html` 顶部填入有效的 Firebase 配置，模式自动切为云端，**演示账号立即失效**——云端模式不会创建任何种子账号，只有真实注册的账号可用。

**如何重置**：

1. 管理后台（演示模式）顶部「**清空本地演示账号**」按钮，二次确认后清空 `wb_local_accounts` 与 `wb_local_session` 并回到登录页；
2. 或右上角头像菜单「**♻ 重置演示账号**」，效果相同。

两者都**只清账号与登录会话**，组织树展开状态、常用报表、数据源偏好等其它 localStorage 数据会保留（确认弹窗中已写明）。

### 5.1 能力清单

- **邮箱密码注册/登录**（Firebase Authentication，Email/Password provider）
- **密码强度提示**（≥8 位，<10 位显示中等等级，≥10 位强）
- **记住会话**：刷新不需重新登录（依赖 Firebase Auth 持久化）
- **用户档案**（Cloud Firestore `users/{uid}`）：`uid / email / displayName / role(user|admin) / status(active|disabled) / createdAt / lastLoginAt`
- **首注册用户自动管理员**：由 `functions/onAuthCreate` 在注册事件时检查 users 集合数量是否为 0 → 是则置 `role='admin'`，否则 `role='user'`
- **管理员后台**（左侧导航数据板块/分析板块之后的「管理」分组，第 11 个页面，仅管理员可见）
  - 用户列表表格 + 改角色 / 启停账号 + 最后登录时间
  - **防锁死**：禁止管理员降级自己或禁用自己
  - **实时联动**：用户被管理员禁用 → 该用户实时监听触发 → 自动退出到登录卡片（云端模式走 Firestore `onSnapshot`；演示模式走 `storage` 事件，跨标签页同步踢出）
- **Firestore 安全规则**（`firestore.rules`）
  - 所有登录用户可读自己的 `users/{uid}`；管理员可读所有
  - 自己只能改 `displayName`；管理员可改 `role / status / displayName`
  - 其它集合一律 deny
- **Cloud Functions**（`functions/index.js`）：`onAuthCreate` + callable `setUserRole`

### 5.2 一次性部署

完整步骤见 [`FIREBASE-SETUP.md`](./FIREBASE-SETUP.md)：包括创建 Firebase 项目、开启 Email/Password 与 Firestore、升级 Blaze、`firebase use --add`、`firebase deploy --only firestore:rules,firestore:indexes,functions`、把 `firebaseConfig` 填到 `index.html` `<head>` 占位符中。

### 5.3 本地联调（无真实项目）

仓库自带完整 Firebase CLI 配置（`firebase.json`）。本地装好 `firebase-tools` 后：

```bash
firebase emulators:start --only auth,firestore,functions --project demo-wb
# 另开一个终端
python3 -m http.server 8000
# 访问 http://localhost:8000/?emulator=1
```

URL 中的 `?emulator=1` 让客户端 SDK 连接本地 emulator；首注册用户自动成为管理员。详见 [`FIREBASE-TEST.md`](./FIREBASE-TEST.md)。

### 5.4 安全模型

- 客户端永远拿不到 admin SDK；`role`/`status` 字段在 Firestore 规则中受保护，仅管理员可写。
- Callable `setUserRole` 在函数内部校验 `req.auth.uid` 对应文档的 `role==='admin'`，避免前端绕过规则提权。
- 用户档案 `create` 权限在规则中设为 `false`，只允许 Cloud Functions（使用 admin SDK）创建，杜绝前端直接伪造首用户。

## 六、质量与自查

- 单文件 `index.html`（内联 CSS/JS），无构建依赖；除 ECharts CDN 与 Firebase compat JS（CDN）外不请求任何外部服务，无密钥（真实 Firebase 配置由用户填入；WorkBuddy Client Secret 仅存 Firebase Secret Manager，全仓扫描确认未入库）。
- 所有 ECharts 容器均有显式高度；隐藏页图表在页面切换时 resize，不存在 0 高度初始化问题。
- 已用无头浏览器（Playwright/Chromium）实测：原 10 个页面、组织树下钻与三模式切换、用户/任务筛选与分页、行内详情展开、分类下钻、报表生成/保存/应用、5 种时间筛选、自定义区间、天/周/月粒度切换、窗口 resize；以及登录/注册、首用户管理员、第二个用户普通、admin 提升/禁用、被禁用账号实时踢出——**无 JS 报错、无 console 报错**。
- 双轨鉴权 + 演示账号 E2E `tests/e2e-dual-auth.py`（96 项断言，真实本地 `http.server` + 占位配置 / 假合法配置两个站点）：种子管理员自动写入且口令为 salt+SHA-256 无明文、一键登录即管理员、注册第二账号为普通用户、四种报错、刷新会话保持、管理员提权/禁用/启用、被禁账号登录被拒、跨标签页在线踢出、防锁死、10 页 + 时间筛选 + CSV + 保存报表回归、真实数据源置灰拦截、清空演示账号后「刷新→种子重生 / 立刻注册→首个为管理员」两条分支；云端模式 SDK 缺失 / 初始化失败均显示友好错误卡片、不白屏、**不创建种子账号**、一键降级可用——全部 PASS。内联 JS 语法用 `tests/extract-inline-js.py` 抽取后 `node --check` 通过。
- Open API 接入逻辑单测 `tests/wb-oauth-mock.js`（55 项断言：authorize URL 字节级 redirect_uri 一致、换 token 表单字段、classifyTaskName 18 样本、扫描逻辑自检）全部 PASS；真实 Client Secret 泄漏扫描用 `tests/secret-scan.js`（secret 从环境变量 `WB_SCAN_SECRET` 或 `~/wb-secret.txt` 读取，仓库内零 secret），最近实测全仓（含 git 历史）CLEAN；真实 API 线上验证清单见 `FIREBASE-TEST.md` D 节。
