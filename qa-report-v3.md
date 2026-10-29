# QA 独立验证报告 v3 — WorkBuddy Open API 双数据源接入

> 验证人：software-qa-engineer-3（严过关）｜日期：2026-09-30
> 定位：与工程师完全独立的第三方验证。不使用工程师的 mock（自建 `qa/firebase-mock-v3.js`，任务字段名/状态值刻意不同）、不复用工程师脚本（自建 `qa/e2e-datasource-v3.py`）、自建扫描器与规则测试。

## 结论（TL;DR）

**不建议直接推 GitHub Pages —— 存在 2 个 P1 问题需先修复**：

| # | 级别 | 问题 | 证据 |
| --- | --- | --- | --- |
| P1-1 | **P1（安全）** | **Client Secret 以「分段明文」形式存在于仓库测试文件** `tests/wb-oauth-mock.js` L131：`['jG▓▓','▓iU3','Te▓▓','▓hEZ','iRS▓▓▓▓▓▓▓▓▓'].join('')（已脱敏）` 即得完整 Secret。任何能读仓库的人（GitHub Pages 项目通常为公开仓库）可在 10 秒内重组出 Client Secret，违反 `FIREBASE-SETUP.md` §7.1 自己声明的「严禁写进任何仓库文件」 | 代码行原文 + 重组验证 |
| P1-2 | **P1（功能）** | **OAuth 授权成功后回跳到站点根（404）而非看板**：`oauth/callback/index.html` 中 `location.href='../../'`（成功回跳，L92）与 `backBtn href='../../'`（L72/L111）在 `https://pyt083.github.io/workbuddy-analytics/oauth/callback` 基址下，浏览器实际解析为 `https://pyt083.github.io/`（GitHub Pages 返回 "Site not found"），不是看板 `/workbuddy-analytics/`。原因：相对路径少算一级——文档名 `callback` 本身占一级，基目录是 `/workbuddy-analytics/oauth/`，两级 `..` 退到站点根。正确应为 `'../'` 或绝对路径 `/workbuddy-analytics/` | S4.10 / S9.7 两处独立浏览器实测（真实 Chromium URL 解析） |

工程师自称 `IS_PASS: YES` 的结论**在这两点上不成立**：其单测对 P1-2 只断言了字符串 `'../../'` 存在（"回调页跳回 ../../ （主页）"），E2E 只测了回调页两条失败路径、未测授权成功后的回跳落点——正是漏检原因。

**除上述两点外，其余全部通过**（详见下文矩阵）。

---

## 一、验证方法与用例矩阵

### 1. Secret 安全（最高优先级）

| 用例 | 手段 | 结果 |
| --- | --- | --- |
| 全仓多形态扫描（明文/大小写/反转/base64 标准+去填充+反转 base64/hex 大小写 × 完整与前缀），排除 .git/node_modules，**含 git 历史全部 blob**（1 commit / 2 blob） | 自建 `qa/secret-scan-v3.py` | **PASS**（18 文件 + 历史 blob，0 命中） |
| `functions/index.js` 无硬编码 Secret，仅 `defineSecret('WB_CLIENT_SECRET')` + `.value()` | 代码审查（L30/44/215/238/250/281/331） | **PASS** |
| callable 返回字段白名单：`wbOauthCallback → {openId, nickname}`；`wbGetMyTasks → {source, tasks, total, openId, profile}`；`wbDisconnect → {ok}`，均不含 access_token / refresh_token | 代码审查（L273/318/341） | **PASS** |
| `firestore.rules` wb_tokens 集合客户端完全 deny（登录/未登录/管理员 × get/list/update/create/delete，共 7 组）+ 用户伪造 `users/{uid}.wbOpenId` 关联 → deny | 自建 `@firebase/rules-unit-testing` 测试（真 Firestore 模拟器 + 仓库真实 rules，种子含模拟 token 文档） | **PASS 9/9** |
| **例外（即 P1-1）**：tests/wb-oauth-mock.js 分段字符串可重组完整 Secret | 代码审查 L131 | **FAIL（P1-1）** |

### 2. OAuth 协议正确性

| 用例 | 手段 | 结果 |
| --- | --- | --- |
| authorize URL：response_type=code、client_id、redirect_uri 解码后与登记地址字节级一致且 `:` `/` 均被编码、scope、state ≥16 字符 | S4.3–S4.9（拦截真实导航请求逐字段断言） | **PASS 7/7** |
| state 防 CSRF 绑定（sessionStorage ↔ URL state 一致） | S4 全链路往返：state 不一致时回调页拒绝（S9.8/9.9），一致时成功（S9.1–9.2），同源同 tab 真实 sessionStorage | **PASS** |
| token 交换表单 5 字段（grant_type=authorization_code/code/client_id/client_secret/redirect_uri）、client_secret 仅参数传入 | 复核工程师单测（51/51 复跑通过）+ 代码审查 L113-121 | **PASS** |
| refresh 分支 grant_type=refresh_token、透传 refresh_token、无 code 字段 | 同上（L124-132） | **PASS** |
| 翻页拉取：size=100、page 递增、上限 500 截断 | 代码审查（L289-312：`tasks.length < 500` 循环 + `slice(0,500)`，退出条件含 batch<size 或 ≥total） | **PASS** |
| 401 时序：先 refresh 再重试**一次**当前页（`retried` 标志防死循环；再次 401 抛 external，不会无限循环） | 代码审查（L291-311） | **PASS** |
| token 过期前 60s 提前刷新（`expiresAt > now+60000` 判定） | 代码审查（L206-209） | **PASS** |

### 3. 前端 E2E（自建 mock，字段名/状态值与工程师 mock 刻意不同）

自建 `qa/firebase-mock-v3.js`：任务用 `title`/`id` 字段（工程师用 `name`/`task_id`）→ 验证前端字段回退链；状态值混合大小写（`Completed`/`FAILED`/`CANCELLED`/`succeeded`/undefined）→ 验证归一化；8 条任务中 1 条 200 天前 → 验证时间筛选。**87 项检查：85 PASS / 2 FAIL（两处均为 P1-2 证据）**

| 节 | 用例 | 结果 |
| --- | --- | --- |
| S1 | 未登录点真实源 → 拦截提示，仍 Mock，不写 real 偏好（3） | PASS |
| S2 | 注册登录（首用户 admin），Mock 基线 4412 条任务（3） | PASS |
| S3 | 未授权切真实源 → 引导卡片 + 去授权按钮 + 错误提示 + 偏好回写 mock（5） | PASS |
| S4 | **OAuth 全链路往返**（主页→authorize[URL 逐字段]→回调页→wbOauthCallback 收到正确 code/redirectUri→写偏好→回跳） | 13 项中 12 PASS；**S4.10 FAIL = P1-2 证据**（实际落点 `https://pyt083.github.io/`） |
| S5 | 真实源渲染：字段回退（title/id）、8 类分类映射、8 种状态值映射、rounds/outs/ups 置 0、授权账号用户、profile 昵称、本周 7 条/自定义宽区间 8 条（时间筛选）、任务表含真实 ID/标题、4 页 API 提示条、CSV 导出、偏好 real（21） | PASS |
| S6 | **切换稳定性**：Mock↔Real 3 轮 + 期间施加筛选/翻页，每轮回 Mock 后 `JSON.stringify(TASKS)` 与基线**逐字节相等**；刷新页面重登后仍相等（固定种子）（8+4） | PASS（工程师修复的惰性缓存确认有效） |
| S7 | 真实源登出 → 自动回退 Mock + 回登录页；重登 → 按偏好自动恢复真实源；token 失效重登 → 回退 Mock + 引导卡片重现（6） | PASS |
| S8 | 断开授权：confirm 接受 → wbDisconnect 调用 → 回退 Mock + 偏好 mock（3） | PASS |
| S9 | 回调页：happy path（成功文案/callable 参数/state 清除/偏好 real）、state 不匹配、无 code、error 参数、未登录、retryBtn 新 state（18） | 17 PASS；**S9.7 FAIL = P1-2 证据**（与 S4.10 交叉印证） |
| — | 主页面/回调页无 JS 报错 | PASS |

### 4. 回归与复核

| 用例 | 结果 |
| --- | --- |
| 工程师单测 `tests/wb-oauth-mock.js` 复跑 | **PASS 51/51**（与自报一致） |
| 工程师 15 节回归 E2E `tests/e2e-auth-admin.py` 复跑 | **PASS**（含原 11 节登录/管理员/防锁死 + 数据源 12-15 节，PAGE ERRORS/CONSOLE ERRORS 均空） |

### 5. 文档可执行性

| 检查 | 结果 |
| --- | --- |
| FIREBASE-SETUP.md §7 闭环：7.1 secrets:set → 7.2 deploy（含 grantaccess 提示）→ 7.3 三处 WB_REDIRECT_URI 字节级核对 + scope → 7.4 回调页 Firebase 配置 → 7.5 线上验证流程 → 7.6 token 安全模型速查 | **PASS**（命令完整、可执行；§8 故障排查含 redirect_uri 不匹配/state 失效/failed-precondition 等场景） |
| FIREBASE-TEST.md D 节线上核对清单 | **PASS（可操作）**：每项有明确步骤与预期（DevTools 查 localStorage、Firestore 控制台查 wb_tokens、控制台执行 collection get 验证 deny、改 expiresAt 验证刷新、撤销授权验证引导重现等）。**小差异**：实际 22 个 checkbox（任务书口径 26 项），数量口径不影响可操作性 |
| README.md 第四节双源说明、§三部署含 oauth/callback/index.html 必需文件 | **PASS** |

### 6. 本地无法验证、由 D 节清单覆盖（不臆测结论）

真实 workbuddy.cn 授权/换 token/翻页/刷新行为（需用户线上授权）→ 已确认 D.0–D.5 共 22 项清单完整覆盖（含 token 服务端持有三点安全验证、token 刷新、撤销授权），**留待用户线上执行**。

---

## 二、问题清单

### P1-1（安全）Client Secret 可从仓库测试文件重组
- **位置**：`tests/wb-oauth-mock.js` L131：
  ```js
  const SECRET = ['jG▓▓','▓iU3','Te▓▓','▓hEZ','iRS▓▓▓▓▓▓▓▓▓▓']（已脱敏）.join('');
  ```
- **影响**：读取仓库者（GitHub Pages 项目通常为公开仓库）可直接拼出完整 Client Secret。分段拼接只是绕过了自家扫描器的** contiguous 明文匹配**，不构成任何安全边界。违反 FIREBASE-SETUP.md §7.1「严禁写进任何仓库文件」。
- **建议修复**（工程师执行）：扫描目标改为从环境变量（`process.env.WB_CLIENT_SECRET`）或仓库外的本地文件读取；或改为结构性断言（如校验仓库中不存在 `client_secret` 赋值模式）。同时建议在 WorkBuddy 开放平台**轮换该 Secret**（已入库即视为暴露）。

### P1-2（功能）授权成功后回跳站点根（404）
- **位置**：`oauth/callback/index.html` L92（`setTimeout(... location.href='../../' ...)`）、L72/L111（`backBtn`/`retryBtn` 邻近的返回链接 `../../`）。
- **实测证据**：Chromium 真实 URL 解析（两处独立用例）：
  - S4.10（全链路往返）：授权成功 → 回跳 `https://pyt083.github.io/`（GitHub Pages "Site not found"）≠ 期望 `/workbuddy-analytics/`
  - S9.7（回调页独立）：同样落点为 `https://pyt083.github.io/`
- **影响**：用户完成 OAuth 授权后落在 404 页，需手动改 URL 回看板（偏好 `wb_data_source=real` 已写入，回看板后功能正常——数据不丢，纯体验断裂，主流程最后一公里）。
- **建议修复**：`'../../'` → `'../'`（或稳妥起见绝对路径 `'/workbuddy-analytics/'`）；同页 `backBtn` 的 href 同步修改；工程师单测相应断言从「字符串存在」升级为「解析后的绝对地址」。

### P3（备注，不阻塞）
- `functions/index.js` `mapWbStatus` 未覆盖 `'closed'`（前端 `mapApiTaskStatus` 有）；该服务端函数当前未被业务路径使用（返回原始 tasks 由前端映射），无实际影响。
- FIREBASE-TEST.md D 节 checkbox 数 22（vs 任务书口径 26），建议统一口径。

---

## 三、测试资产（本次新增，均落 qa/ 或沙箱）

| 文件 | 说明 |
| --- | --- |
| `qa/secret-scan-v3.py` | 多形态 Secret 扫描（含 git 历史 blob） |
| `qa/firebase-mock-v3.js` | 独立 mock（字段名/状态值与工程师 mock 刻意不同 + callable 调用记录） |
| `qa/e2e-datasource-v3.py` | 独立 E2E 87 项（含 OAuth 全链路往返、3 轮切换稳定性、回调页 6 场景） |
| `/tmp/wbqa-v3/wb-tokens-rules-v3.test.js` | wb_tokens 规则 9 项（Firestore 模拟器；如需留仓可移入 qa/） |

运行方式：
```bash
python3 qa/secret-scan-v3.py                       # Secret 扫描
python3 qa/e2e-datasource-v3.py                    # 独立 E2E（87 项）
node tests/wb-oauth-mock.js                        # 工程师单测复核
python3 tests/e2e-auth-admin.py                    # 回归 E2E
# 规则测试：在 /tmp/wbqa-v3 下
firebase emulators:exec --project demo-wbqa-v3 --only firestore \
  "FIRESTORE_EMULATOR_HOST=127.0.0.1:8081 node wb-tokens-rules-v3.test.js"
```

## 四、总评

- 双数据源的核心架构（token 服务端持有、规则 deny、OAuth 参数、字段映射、切换稳定性、偏好恢复）**质量扎实**，工程师 51 单测 + 15 节 E2E 自报结果属实（已复跑确认）。
- 但**独立视角发现了工程师测试盲区的 2 个 P1**：①Secret 以分段形式可重组（其自扫描天然测不出——扫描目标本身就在仓库里）；②回跳相对路径层级错误（其单测只查字符串、E2E 未走 happy path 落点）。
- **放行条件：修复 P1-1、P1-2 并复跑本报告三项资产（secret-scan / e2e-datasource / rules）全绿后，可推 GitHub Pages；线上行为按 D 节 22 项清单由用户核对。**
