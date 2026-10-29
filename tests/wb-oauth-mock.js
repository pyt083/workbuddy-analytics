/**
 * tests/wb-oauth-mock.js — WorkBuddy Open API 接入逻辑单测（node 直接运行，零外部依赖）
 *
 * 覆盖：
 *   1) 前端 authorize 重定向 URL 拼接：redirect_uri 与登记地址字节级一致（URL 编码正确）、
 *      scope / response_type / client_id / state 齐全且 state 被编码
 *   2) oauth/callback/index.html 内同名逻辑与主页一致（回调地址常量字节级一致）
 *   3) functions/index.js wbOauthCallback 换 token 表单字段正确
 *      （grant_type=authorization_code + code + client_id + client_secret + redirect_uri），
 *      refresh 分支字段正确，且 client_secret 由参数传入（代码不硬编码）
 *   4) classifyTaskName 覆盖 8 个类别样本 + 默认「其他」
 *   5) Client Secret 绝不出现在仓库任何文件中（全仓扫描）
 *
 * 运行：node tests/wb-oauth-mock.js
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const results = [];
let failed = 0;
function check(name, ok, evidence) {
  results.push([ok, name]);
  if (!ok) failed++;
  console.log('  [' + (ok ? 'PASS' : 'FAIL') + '] ' + name + (evidence ? '  | ' + evidence : ''));
}

/* ---------- 读取源文件 ---------- */
const indexHtml = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
const callbackHtml = fs.readFileSync(path.join(ROOT, 'oauth/callback/index.html'), 'utf8');

/* ---------- 1) 提取主页 WB-OAUTH-TESTABLE 块并求值 ---------- */
const m = indexHtml.match(/\/\* ==== WB-OAUTH-TESTABLE-BEGIN ====.*?\n([\s\S]*?)\/\* ==== WB-OAUTH-TESTABLE-END ==== \*\//);
check('index.html 含 WB-OAUTH-TESTABLE 块', !!m);
// eval 后取回导出（通过 Function 作用域返回）
const fe = new Function(m ? m[1] + '\n;return {WB_CLIENT_ID:WB_CLIENT_ID,WB_REDIRECT_URI:WB_REDIRECT_URI,WB_SCOPES:WB_SCOPES,buildWbAuthorizeUrl:buildWbAuthorizeUrl,classifyTaskName:classifyTaskName};' : 'return {};')();
check('WB-OAUTH-TESTABLE 块可独立求值', !!(fe && fe.buildWbAuthorizeUrl));

const REGISTERED_REDIRECT = 'https://pyt083.github.io/workbuddy-analytics/oauth/callback';
check('前端 WB_REDIRECT_URI 与登记回调地址字节级一致', fe.WB_REDIRECT_URI === REGISTERED_REDIRECT,
  fe.WB_REDIRECT_URI);

/* ---------- 2) authorize URL 拼接正确性 ---------- */
const stateTok = 'st_ABC123xyz+/=';
const url = fe.buildWbAuthorizeUrl(stateTok);
const u = new URL(url);
check('authorize URL 基于 /openapi/v2/authorize', u.origin + u.pathname === 'https://www.workbuddy.cn/openapi/v2/authorize');
check('response_type=code', u.searchParams.get('response_type') === 'code');
check('client_id 正确', u.searchParams.get('client_id') === 'cb_YipjG5TEevNZFIblffrL', u.searchParams.get('client_id'));
check('redirect_uri 解码后与登记地址字节级一致', u.searchParams.get('redirect_uri') === REGISTERED_REDIRECT,
  u.searchParams.get('redirect_uri'));
check('redirect_uri 原始编码正确（: 与 / 均被编码）', /redirect_uri=https%3A%2F%2F/.test(url));
check('scope 含 user.profile.readable + user.task.readable', u.searchParams.get('scope') === 'user.profile.readable user.task.readable',
  u.searchParams.get('scope'));
check('state 原样往返（含特殊字符）', u.searchParams.get('state') === stateTok);
check('state 在原始 URL 中被编码', url.indexOf(encodeURIComponent(stateTok)) > -1);

/* ---------- 3) oauth/callback/index.html 与主页一致性 ---------- */
const cb = callbackHtml.match(/var WB_REDIRECT_URI='([^']+)'/);
check('回调页 WB_REDIRECT_URI 常量与登记地址一致', !!cb && cb[1] === REGISTERED_REDIRECT, cb ? cb[1] : '(未找到)');
check('回调页含 state 校验逻辑（sessionStorage wb_oauth_state）', /wb_oauth_state/.test(callbackHtml));
check('回调页成功后写 localStorage wb_data_source=real', /localStorage\.setItem\('wb_data_source','real'\)/.test(callbackHtml));
check('回调页跳回主页（绝对路径 /workbuddy-analytics/，不依赖相对层级）', /location\.href=WB_HOME/.test(callbackHtml) && /var WB_HOME='\/workbuddy-analytics\/'/.test(callbackHtml));

/* ---------- 4) functions/index.js：wbOauthCallback 换 token 表单字段 ---------- */
process.env.FUNCTIONS_EMULATOR = 'skip'; // 不影响 require，仅避免意外真连
const fnMod = require(path.join(ROOT, 'functions/index.js'));
const t = fnMod.__testables || {};
check('functions __testables 可用', !!(t.buildAuthCodeExchange && t.buildRefreshExchange && t.buildTokenFormBody));

check('服务端 WB_REDIRECT_URI 与登记地址字节级一致', t.WB_REDIRECT_URI === REGISTERED_REDIRECT, t.WB_REDIRECT_URI);
check('服务端 WB_CLIENT_ID 与前端一致', t.WB_CLIENT_ID === 'cb_YipjG5TEevNZFIblffrL');

// 授权码换 token：字段与值
const FAKE_SECRET = 'YOUR_CLIENT_SECRET';
const exch = t.buildAuthCodeExchange('CODE_XYZ', REGISTERED_REDIRECT, FAKE_SECRET);
const exchKeys = Object.keys(exch).sort().join(',');
check('auth code 交换表单字段齐全（5 项）', exchKeys === 'client_id,client_secret,code,grant_type,redirect_uri', exchKeys);
check('grant_type=authorization_code', exch.grant_type === 'authorization_code');
check('code 透传', exch.code === 'CODE_XYZ');
check('client_id 正确', exch.client_id === 'cb_YipjG5TEevNZFIblffrL');
check('client_secret 由调用方传入（不硬编码）', exch.client_secret === FAKE_SECRET);
check('redirect_uri 与登记地址字节级一致', exch.redirect_uri === REGISTERED_REDIRECT);

// 表单体编码
const body = t.buildTokenFormBody(exch);
const bp = new URLSearchParams(body);
check('表单体 round-trip 后字段值不丢失', bp.get('redirect_uri') === REGISTERED_REDIRECT && bp.get('code') === 'CODE_XYZ' && bp.get('client_secret') === FAKE_SECRET);
check('表单体 Content-Type 为 application/x-www-form-urlencoded 可解析', bp.get('grant_type') === 'authorization_code');

// refresh 分支
const refr = t.buildRefreshExchange('RTOK_1', FAKE_SECRET);
check('refresh 表单 grant_type=refresh_token', refr.grant_type === 'refresh_token');
check('refresh 表单透传 refresh_token', refr.refresh_token === 'RTOK_1');
check('refresh 表单 client_secret 由调用方传入', refr.client_secret === FAKE_SECRET);

// 状态映射
const st = t.mapWbStatus;
check('mapWbStatus completed→已完成', st('completed') === '已完成' && st('done') === '已完成');
check('mapWbStatus cancelled/failed→已取消', st('cancelled') === '已取消' && st('failed') === '已取消');
check('mapWbStatus running/空→进行中', st('running') === '进行中' && st('') === '进行中');

/* ---------- 5) classifyTaskName 各类别样本 ---------- */
const cases = [
  ['帮我把这份季度经营分析写成 PPT 汇报幻灯片', 'PPT制作'],
  ['制作一份产品发布会的 slides', 'PPT制作'],
  ['把这段中文市场调研翻译成英文', '翻译'],
  ['翻译下面这段合同条款', '翻译'],
  ['生成一张活动宣传海报', '图片设计'],
  ['帮我设计一个 logo 和 banner', '图片设计'],
  ['把这篇公众号文章做成短视频脚本', '视频生成'],
  ['剪辑一段 30 秒的产品演示视频', '视频生成'],
  ['写一个爬虫脚本抓取数据', '代码开发'],
  ['帮我修复这个 Python 接口的 bug', '代码开发'],
  ['统计上季度销售数据并做可视化分析', '数据分析'],
  ['输出各部门周活跃用户报表', '数据分析'],
  ['起草一份项目验收报告', '文档写作'],
  ['帮我写一封商务合作邮件', '文档写作'],
  ['整理今天的会议纪要', '文档写作'],
  ['陪我聊聊天放松一下', '其他'],
  ['TODO 待定任务', '其他'],
  ['', '其他']
];
cases.forEach(function (c) {
  check('classifyTaskName「' + (c[0] || '(空)') + '」→ ' + c[1], fe.classifyTaskName(c[0]) === c[1],
    '实际=' + fe.classifyTaskName(c[0]));
});

/* ---------- 6) Secret 扫描逻辑自检（不内置任何真实 secret 片段） ---------- */
// 仓库内测试只验证「扫描逻辑本身」可用：用假 secret 造一个临时泄漏文件 → 必须被检出 → 删除后全仓必须 clean。
// 真实 Client Secret 的扫描用 tests/secret-scan.js：secret 从环境变量 WB_SCAN_SECRET 或 ~/wb-secret.txt 读取
// （绝不进入仓库，见 FIREBASE-TEST.md「Secret 泄漏扫描」节）。
const SCAN_PROBE = 'test-secret-placeholder-xyz-FAKE-0001';

function scanRepoFor(needleList) {
  const hits = [];
  (function walk(dir) {
    fs.readdirSync(dir).forEach(function (name) {
      if (name === '.git' || name === 'node_modules') return;
      const p = path.join(dir, name);
      if (p === __filename) return; // 排除扫描工具自身（FAKE 常量在此定义）
      const stt = fs.statSync(p);
      if (stt.isDirectory()) return walk(p);
      const buf = fs.readFileSync(p);
      if (needleList.some(function (nd) { return buf.indexOf(nd) > -1; })) hits.push(p);
    });
  })(ROOT);
  return hits;
}
const FAKE_NEEDLES = [Buffer.from(SCAN_PROBE, 'utf8'), Buffer.from(SCAN_PROBE, 'utf8').toString('base64')];

// 6a) 全仓当前不含假 secret（基线 clean）
check('扫描基线：全仓不含假 secret（除本文件）', scanRepoFor(FAKE_NEEDLES).length === 0);

// 6b) 造临时泄漏文件 → 扫描必须检出（明文与 base64 两种形态）
const tmpLeak = path.join(ROOT, '.tmp-leak-scan-test.txt');
try {
  fs.writeFileSync(tmpLeak, 'oops leak: ' + SCAN_PROBE);
  check('扫描逻辑能检出明文泄漏', scanRepoFor([Buffer.from(SCAN_PROBE, 'utf8')]).indexOf(tmpLeak) > -1);
  fs.writeFileSync(tmpLeak, 'oops leak: ' + Buffer.from(SCAN_PROBE, 'utf8').toString('base64'));
  check('扫描逻辑能检出 base64 泄漏', scanRepoFor([Buffer.from(SCAN_PROBE, 'utf8').toString('base64')]).indexOf(tmpLeak) > -1);
} finally {
  try { fs.unlinkSync(tmpLeak); } catch (e) { /* 已删除 */ }
}
check('临时泄漏文件已清理', !fs.existsSync(tmpLeak));
check('清理后全仓恢复 clean', scanRepoFor(FAKE_NEEDLES).length === 0);

/* ---------- 汇总 ---------- */
console.log('\n总计: ' + results.length + ' 项，失败: ' + failed);
if (failed > 0) {
  console.log('OVERALL: FAIL');
  process.exit(1);
} else {
  console.log('OVERALL: PASS');
}
