/**
 * WorkBuddy 数据分析平台 Cloud Functions
 * - onAuthCreate：用户注册成功后，bootstrap 一条 users/{uid} 档案；
 *                若数据库尚无任何用户则置 role='admin'（首用户为管理员），
 *                否则置 role='user'（普通用户）。
 * - setUserRole (callable)：仅管理员可调用，修改任意用户的 role。
 * - wbOauthCallback (callable)：WorkBuddy 开放平台 OAuth2.1 授权码换 token，
 *                token 全程服务端持有（存 /wb_tokens/{open_id}，不返回浏览器）。
 * - wbGetMyTasks (callable)：服务端代当前用户刷新 token（如需）并翻页拉取
 *                GET /openapi/v2/tasks 全量任务（上限 500 条）。
 * - wbDisconnect (callable)：删除当前用户的 wb_tokens 文档，断开授权。
 *
 * Secret 安全：WB_CLIENT_SECRET 通过 Firebase Secret Manager 注入
 *   （firebase functions:secrets:set WB_CLIENT_SECRET），代码绝不硬编码。
 *
 * Firestore 安全规则约束（见 firestore.rules）：
 *   users/{uid} 的 create 仅允许服务端（rule: allow create: if false），
 *   wb_tokens 集合对客户端完全 deny；本组函数使用 admin SDK 写入，绕过规则。
 */

const { onCall, HttpsError } = require('firebase-functions/v2/https');
const { initializeApp } = require('firebase-admin/app');
const { getFirestore, FieldValue } = require('firebase-admin/firestore');
const { getAuth } = require('firebase-admin/auth');
const { setGlobalOptions } = require('firebase-functions/v2');
// 注：Auth 触发器在 firebase-functions@5.x 只有 v1 API，
//     `v2/auth` 子路径不存在，会导致 ERR_PACKAGE_PATH_NOT_EXPORTED。
const functionsV1 = require('firebase-functions/v1');
// Client Secret 走 Secret Manager（defineSecret 在 v2 params 子路径）。
const { defineSecret } = require('firebase-functions/params');

initializeApp();
setGlobalOptions({ region: 'us-central1' });
const db = getFirestore();

/* ===== WorkBuddy 开放平台常量（Client ID 可公开进前端；Secret 绝不进代码） ===== */
const WB_API_HOST = 'https://www.workbuddy.cn';
const WB_CLIENT_ID = 'cb_YipjG5TEevNZFIblffrL';
// 必须与 WorkBuddy 第三方应用后台登记的重定向 URI 字节级一致
const WB_REDIRECT_URI = 'https://pyt083.github.io/workbuddy-analytics/oauth/callback';
const WB_TASKS_MAX = 500;      // 拉取任务上限
const WB_TASKS_PAGE_SIZE = 100; // 单页 size
// Secret 引用：部署前执行 firebase functions:secrets:set WB_CLIENT_SECRET
const WB_CLIENT_SECRET = defineSecret('WB_CLIENT_SECRET');

/** 首注册用户为管理员：检查 users 集合数量是否为 0 */
exports.onAuthCreate = functionsV1.auth.user().onCreate(async (user) => {
  const uid = user.uid;
  const email = user.email || '';
  const displayName = user.displayName || '';

  // 用户档案已存在则跳过（幂等）
  const userRef = db.collection('users').doc(uid);
  const snap = await userRef.get();
  if (snap.exists) {
    await userRef.update({ lastLoginAt: FieldValue.serverTimestamp() });
    return;
  }

  // 计算是否为首位用户
  const usersSnap = await db.collection('users').count().get();
  const isFirst = (usersSnap.data().count === 0);
  const role = isFirst ? 'admin' : 'user';

  await userRef.set({
    uid,
    email,
    displayName,
    role,
    status: 'active',
    createdAt: FieldValue.serverTimestamp(),
    lastLoginAt: FieldValue.serverTimestamp(),
  });
});

/** 调用方需为 admin；修改目标用户的 role */
exports.setUserRole = onCall(async (req) => {
  if (!req.auth) throw new HttpsError('unauthenticated', '需要登录');
  const callerUid = req.auth.uid;
  const callerDoc = await db.collection('users').doc(callerUid).get();
  if (!callerDoc.exists || callerDoc.data().role !== 'admin') {
    throw new HttpsError('permission-denied', '需要管理员权限');
  }
  const { uid, role } = req.data || {};
  if (!uid || !role || (role !== 'admin' && role !== 'user')) {
    throw new HttpsError('invalid-argument', '参数错误');
  }
  // 防锁死：禁止管理员降级自己
  if (uid === callerUid && role === 'user') {
    throw new HttpsError('failed-precondition', '不能被降级自己（防锁死）');
  }
  const targetDoc = await db.collection('users').doc(uid).get();
  if (!targetDoc.exists) throw new HttpsError('not-found', '用户不存在');
  await db.collection('users').doc(uid).update({ role });
  return { ok: true, uid, role };
});

/* =========================================================================
 * WorkBuddy 开放平台 OAuth2.1 接入
 * - token 全程服务端持有：交换/刷新后存 Firestore /wb_tokens/{open_id}，
 *   并在 users/{uid} 记 wbOpenId 关联；access_token/refresh_token 绝不返回浏览器。
 * - 浏览器只持有 open_id 标识 + 昵称等非敏感信息。
 * ========================================================================= */

/** 构造 application/x-www-form-urlencoded 请求体（纯函数，便于单测） */
function buildTokenFormBody(params) {
  const body = new URLSearchParams();
  Object.keys(params).forEach(function (k) { body.append(k, params[k]); });
  return body.toString();
}

/** 授权码换 token 的表单参数（纯函数，便于单测；secret 由调用方传入，不落盘） */
function buildAuthCodeExchange(code, redirectUri, clientSecret) {
  return {
    grant_type: 'authorization_code',
    code: code,
    client_id: WB_CLIENT_ID,
    client_secret: clientSecret,
    redirect_uri: redirectUri
  };
}

/** refresh_token 刷新的表单参数（纯函数，便于单测） */
function buildRefreshExchange(refreshToken, clientSecret) {
  return {
    grant_type: 'refresh_token',
    refresh_token: refreshToken,
    client_id: WB_CLIENT_ID,
    client_secret: clientSecret,
    redirect_uri: WB_REDIRECT_URI
  };
}

/** WorkBuddy 任务状态 → 看板展示状态（纯函数，便于单测） */
function mapWbStatus(s) {
  if (!s) return '进行中';
  const v = String(s).toLowerCase();
  if (['completed', 'complete', 'finished', 'done', 'success', 'succeeded', '已完成'].indexOf(v) > -1) return '已完成';
  if (['cancelled', 'canceled', 'failed', 'error', 'abort', '已取消', '失败'].indexOf(v) > -1) return '已取消';
  return '进行中';
}

/** POST /openapi/v2/token，返回解析后的 JSON（非 2xx 抛错并带响应体摘要） */
async function wbPostToken(formParams) {
  const res = await fetch(WB_API_HOST + '/openapi/v2/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: buildTokenFormBody(formParams)
  });
  const text = await res.text();
  let json = {};
  try { json = JSON.parse(text); } catch (e) { /* 保持 {} */ }
  if (!res.ok) {
    throw new HttpsError('external', 'WorkBuddy token 接口返回 ' + res.status +
      '：' + String(text).slice(0, 200));
  }
  return json;
}

/** 用 access_token 调 GET（Bearer）；401 时抛 TokenExpiredError 语义错误 */
async function wbGet(path, accessToken) {
  const res = await fetch(WB_API_HOST + path, {
    headers: { Authorization: 'Bearer ' + accessToken }
  });
  const text = await res.text();
  let json = {};
  try { json = JSON.parse(text); } catch (e) { /* 保持 {} */ }
  if (res.status === 401 || res.status === 403) {
    const err = new Error('WorkBuddy API 返回 ' + res.status);
    err.tokenExpired = true;
    throw err;
  }
  if (!res.ok) {
    throw new HttpsError('external', 'WorkBuddy ' + path + ' 接口返回 ' + res.status +
      '：' + String(text).slice(0, 200));
  }
  return json;
}

/** GET /openapi/v2/user/profile（尽力而为，失败不影响主流程） */
async function wbFetchProfile(accessToken) {
  try {
    const p = await wbGet('/openapi/v2/user/profile', accessToken);
    return {
      nickname: p.nickname || p.nick_name || p.name || '',
      avatar: p.avatar || p.avatar_url || p.headimgurl || ''
    };
  } catch (e) {
    return { nickname: '', avatar: '' };
  }
}

/** 读取并按需刷新当前用户的 token 文档；失败抛需要重新授权的错误 */
async function wbEnsureFreshToken(uid) {
  const userSnap = await db.collection('users').doc(uid).get();
  const openId = userSnap.exists ? (userSnap.data().wbOpenId || '') : '';
  if (!openId) {
    throw new HttpsError('failed-precondition', '尚未授权 WorkBuddy 数据源，请先完成 OAuth 授权');
  }
  const tokenRef = db.collection('wb_tokens').doc(openId);
  const tokenSnap = await tokenRef.get();
  if (!tokenSnap.exists) {
    throw new HttpsError('failed-precondition', '授权信息不存在，请重新授权');
  }
  const tk = tokenSnap.data();
  // 过期前 60 秒内即刷新，避免边界失效
  if (tk.expiresAt && tk.expiresAt > Date.now() + 60000) {
    return { tokenDoc: tk, tokenRef: tokenRef };
  }
  if (!tk.refreshToken) {
    throw new HttpsError('failed-precondition', 'access_token 已失效且无 refresh_token，请重新授权');
  }
  let fresh;
  try {
    fresh = await wbPostToken(buildRefreshExchange(tk.refreshToken, WB_CLIENT_SECRET.value()));
  } catch (e) {
    throw new HttpsError('failed-precondition', 'access_token 已失效且无法刷新，请重新授权');
  }
  if (!fresh.access_token) {
    throw new HttpsError('failed-precondition', 'access_token 已失效且无法刷新，请重新授权');
  }
  const expiresAt = Date.now() + (Number(fresh.expires_in) || 3600) * 1000;
  const newDoc = Object.assign({}, tk, {
    accessToken: fresh.access_token,
    refreshToken: fresh.refresh_token || tk.refreshToken,
    expiresAt: expiresAt,
    updatedAt: FieldValue.serverTimestamp()
  });
  await tokenRef.set(newDoc, { merge: true });
  return { tokenDoc: newDoc, tokenRef: tokenRef };
}

/**
 * callable wbOauthCallback({ code, redirectUri })
 * 授权码换 token → 存 /wb_tokens/{open_id}（含 firebase uid 关联）→ 返回 open_id + 昵称。
 * token 绝不返回浏览器。
 */
exports.wbOauthCallback = onCall({ secrets: [WB_CLIENT_SECRET] }, async (req) => {
  if (!req.auth) throw new HttpsError('unauthenticated', '需要登录');
  const code = req.data && req.data.code;
  const redirectUri = req.data && req.data.redirectUri;
  if (!code) throw new HttpsError('invalid-argument', '缺少授权码 code');
  if (!redirectUri) throw new HttpsError('invalid-argument', '缺少 redirectUri');
  // redirect_uri 必须与授权阶段字节级一致：仅接受登记的回调地址
  if (redirectUri !== WB_REDIRECT_URI) {
    throw new HttpsError('invalid-argument', 'redirectUri 与登记的回调地址不一致');
  }
  const uid = req.auth.uid;

  const tkJson = await wbPostToken(buildAuthCodeExchange(code, redirectUri, WB_CLIENT_SECRET.value()));
  if (!tkJson.access_token) {
    throw new HttpsError('external', 'WorkBuddy 未返回 access_token：' + JSON.stringify(tkJson).slice(0, 200));
  }
  const openId = tkJson.open_id || tkJson.openid || tkJson.sub || uid; // 兼容常见命名
  const expiresAt = Date.now() + (Number(tkJson.expires_in) || 3600) * 1000;
  const profile = await wbFetchProfile(tkJson.access_token);

  // token 存服务端（wb_tokens 对客户端 deny，仅 admin SDK 可写）
  await db.collection('wb_tokens').doc(openId).set({
    openId: openId,
    uid: uid,
    accessToken: tkJson.access_token,
    refreshToken: tkJson.refresh_token || '',
    expiresAt: expiresAt,
    scope: tkJson.scope || '',
    profile: profile,
    createdAt: FieldValue.serverTimestamp(),
    updatedAt: FieldValue.serverTimestamp()
  }, { merge: true });
  // users/{uid} 记录关联（admin SDK 写入，绕过安全规则；客户端规则不放开 wbOpenId）
  await db.collection('users').doc(uid).set({ wbOpenId: openId }, { merge: true });

  return { openId: openId, nickname: profile.nickname || '' };
});

/**
 * callable wbGetMyTasks()
 * 服务端代当前用户：读 wb_tokens → 过期则刷新 → 翻页拉全 GET /openapi/v2/tasks
 * （上限 500 条）→ 返回原始 tasks 数组（token 不出服务器）。
 */
exports.wbGetMyTasks = onCall({ secrets: [WB_CLIENT_SECRET] }, async (req) => {
  if (!req.auth) throw new HttpsError('unauthenticated', '需要登录');
  const uid = req.auth.uid;
  const { tokenDoc } = await wbEnsureFreshToken(uid);

  let tasks = [];
  let total = 0;
  let profile = tokenDoc.profile || { nickname: '', avatar: '' };
  let page = 1;
  let retried = false;
  while (tasks.length < WB_TASKS_MAX) {
    let json;
    try {
      json = await wbGet('/openapi/v2/tasks?page=' + page + '&size=' + WB_TASKS_PAGE_SIZE, tokenDoc.accessToken);
    } catch (e) {
      // 兜底：个别网关在临界过期时才返回 401 —— 刷一次 token 再重试一轮
      if (e.tokenExpired && !retried) {
        retried = true;
        const fresh = await wbEnsureFreshToken(uid); // 内部会刷新并回写
        tokenDoc.accessToken = fresh.tokenDoc.accessToken;
        continue; // 重试当前页
      }
      if (e instanceof HttpsError) throw e;
      throw new HttpsError('external', String(e && e.message || e));
    }
    const batch = Array.isArray(json.tasks) ? json.tasks : [];
    total = Number(json.total != null ? json.total : (tasks.length + batch.length));
    tasks = tasks.concat(batch);
    if (batch.length < WB_TASKS_PAGE_SIZE || tasks.length >= total) break;
    page++;
  }
  if (tasks.length > WB_TASKS_MAX) tasks = tasks.slice(0, WB_TASKS_MAX);

  // profile 尽力刷新一次（token 刚换过，通常有效）
  const p = await wbFetchProfile(tokenDoc.accessToken);
  if (p.nickname) profile = p;

  return {
    source: 'api',
    tasks: tasks,
    total: total,
    openId: tokenDoc.openId || '',
    profile: profile
  };
});

/**
 * callable wbDisconnect()
 * 删除当前用户的 wb_tokens 文档并解除 users/{uid}.wbOpenId 关联。
 */
exports.wbDisconnect = onCall({ secrets: [WB_CLIENT_SECRET] }, async (req) => {
  if (!req.auth) throw new HttpsError('unauthenticated', '需要登录');
  const uid = req.auth.uid;
  const userRef = db.collection('users').doc(uid);
  const userSnap = await userRef.get();
  const openId = userSnap.exists ? (userSnap.data().wbOpenId || '') : '';
  if (openId) {
    await db.collection('wb_tokens').doc(openId).delete();
    await userRef.update({ wbOpenId: FieldValue.delete() });
  }
  return { ok: true };
});

/* 单测导出（不部署为函数：仅在 require 时可见） */
exports.__testables = {
  buildTokenFormBody: buildTokenFormBody,
  buildAuthCodeExchange: buildAuthCodeExchange,
  buildRefreshExchange: buildRefreshExchange,
  mapWbStatus: mapWbStatus,
  WB_CLIENT_ID: WB_CLIENT_ID,
  WB_REDIRECT_URI: WB_REDIRECT_URI
};