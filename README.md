# WorkBuddy 数据分析平台（演示版）

一个**纯静态单页 HTML 看板**，模拟 WorkBuddy 企业后台数据分析场景：约 200 名员工、5 个一级部门（各含 2–3 个二级部门）、90 天使用数据。全部 CSS/JS 内联在单个 `index.html` 中，无需构建、无外部依赖（仅图表库走 CDN），可直接托管到 GitHub Pages。

- 页面顶部平台名：**WorkBuddy 数据分析平台**
- 数据源标识：**演示数据（Mock）**（顶部徽标）
- 图表库：ECharts 5（`https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js`）
- 主题：浅色商务风，主色 `#2563eb`，中文界面，左侧深色导航 + 顶部全局筛选栏 + 右侧内容区

## 一、页面结构（10 个页面，左侧一级导航）

**数据板块**

| 页面 | 说明 |
| --- | --- |
| 1. 总览看板 | 6 个核心指标卡（活跃用户数、任务总数、日均任务数、平均对话轮次、产物生成量、上传资料数，均带环比涨跌）；任务量+活跃用户双轴趋势图（按天/周/月切换）；任务量 Top5 部门、Top10 个人、Top5 类别三个排行榜；底部「API 数据接入指引」卡片 |
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

1. 新建仓库并把 `index.html`（可选连同本 README）推到默认分支，例如 `main`：

   ```bash
   git init
   git add index.html README.md
   git commit -m "feat: WorkBuddy 数据分析平台演示看板"
   git branch -M main
   git remote add origin https://github.com/<your-name>/<repo>.git
   git push -u origin main
   ```

2. 仓库 **Settings → Pages**：Source 选择 `Deploy from a branch`，Branch 选 `main` + `/ (root)`，保存。
3. 稍等 1 分钟，访问 `https://<your-name>.github.io/<repo>/` 即可。

> 说明：单文件内联 CSS/JS，无需构建产物；ECharts 通过 jsDelivr CDN 加载，访问环境需能连通公网 CDN（若内网受限，可把 `echarts.min.js` 下载到同目录并把 `<script src>` 改为相对路径）。

本地预览：直接用浏览器打开 `index.html`，或在目录下执行 `python3 -m http.server 8080` 后访问 `http://localhost:8080/`。

## 四、数据接入说明（Mock → 真实数据）

当前所有数据由内置 **Mock 数据生成器**（固定种子 `mulberry32(20260929)`）生成，**刷新页面数据保持一致**。数据模型：

- **用户**：工号 `WB0001` 起；中文姓名；部门 / 二级部门；岗位（产品经理、设计师、前端/后端/测试工程师、运营、市场专员等）；业务分类（智影 / 智剪 / 智图 / 中台）。
- **任务**：任务 ID `T10001` 起；标题由模板池 × 变量组合生成；任务类别 8 种（文档写作/视频生成/图片设计/数据分析/代码开发/PPT制作/翻译/其他）；对话轮次 1–12；产物数 0–5；上传资料 0–3（带类型）；提示词文本（长度与关键词均从任务数据派生，口径一致）；多轮对话 Mock（按任务 ID 确定性生成）；时间戳近 180 天内随机（**默认筛选窗口为近 90 天**，多出的 90 天作为环比/同周期对比的基线数据）；状态（已完成/进行中/已取消）。

**接入真实数据**：页面统计统一经由 `DataAdapter.load()` 取数，源码中已预留接口层：

```js
var MockDataSource = { name:'演示数据（Mock）', load:function(){ ... } };
var ApiDataSource  = { /* 预留：接入开放平台时实现 load() */ };
var DataAdapter = { source: MockDataSource, load: function(){ return this.source.load(); } };
```

替换步骤：

1. 通过 **WorkBuddy 开放平台 OAuth2.1** 授权：将用户导向授权端点 `https://www.workbuddy.cn/openapi/v2/authorize`，回调拿 `code` 后换取 `access_token`；
2. 调用 **任务列表** `GET /openapi/v2/tasks`（建议带分页/增量参数）拉取任务数据，并按上述数据模型做字段映射；
3. 实现 `ApiDataSource.load()` 返回同结构 `{ users, tasks }`，并把 `DataAdapter.source` 指向 `ApiDataSource`。页面渲染与统计代码无需任何改动，顶部数据源徽标可同步改为「实时数据」。

## 五、登录与管理员后台（Firebase）

页面在未登录时会显示一张居中的登录卡片（原 10 页全部隐藏）。登录后才能进入看板；右上角头像下拉包含「管理后台」（仅管理员可见）与「退出登录」。

### 5.1 能力清单

- **邮箱密码注册/登录**（Firebase Authentication，Email/Password provider）
- **密码强度提示**（≥8 位，<10 位显示中等等级，≥10 位强）
- **记住会话**：刷新不需重新登录（依赖 Firebase Auth 持久化）
- **用户档案**（Cloud Firestore `users/{uid}`）：`uid / email / displayName / role(user|admin) / status(active|disabled) / createdAt / lastLoginAt`
- **首注册用户自动管理员**：由 `functions/onAuthCreate` 在注册事件时检查 users 集合数量是否为 0 → 是则置 `role='admin'`，否则 `role='user'`
- **管理员后台**（左侧导航数据板块/分析板块之后的「管理」分组，第 11 个页面，仅管理员可见）
  - 用户列表表格 + 改角色 / 启停账号 + 最后登录时间
  - **防锁死**：禁止管理员降级自己或禁用自己
  - **实时联动**：用户被管理员禁用 → 该用户实时监听触发 → 自动退出到登录卡片
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

- 单文件 `index.html`（内联 CSS/JS），无构建依赖；除 ECharts CDN 与 Firebase compat JS（CDN）外不请求任何外部服务，无密钥（真实 Firebase 配置由用户填入）。
- 所有 ECharts 容器均有显式高度；隐藏页图表在页面切换时 resize，不存在 0 高度初始化问题。
- 已用无头浏览器（Playwright/Chromium）实测：原 10 个页面、组织树下钻与三模式切换、用户/任务筛选与分页、行内详情展开、分类下钻、报表生成/保存/应用、5 种时间筛选、自定义区间、天/周/月粒度切换、窗口 resize；以及登录/注册、首用户管理员、第二个用户普通、admin 提升/禁用、被禁用账号实时踢出——**无 JS 报错、无 console 报错**。
