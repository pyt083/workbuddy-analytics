/**
 * WorkBuddy 数据分析平台 Cloud Functions
 * - onAuthCreate：用户注册成功后，bootstrap 一条 users/{uid} 档案；
 *                若数据库尚无任何用户则置 role='admin'（首用户为管理员），
 *                否则置 role='user'（普通用户）。
 * - setUserRole (callable)：仅管理员可调用，修改任意用户的 role。
 *
 * Firestore 安全规则约束（见 firestore.rules）：
 *   users/{uid} 的 create 仅允许服务端（rule: allow create: if false），
 *   本函数使用 admin SDK 写入，绕过规则；客户端不能直接 create 用户档案。
 */

const { onCall, HttpsError } = require('firebase-functions/v2/https');
const { initializeApp } = require('firebase-admin/app');
const { getFirestore, FieldValue } = require('firebase-admin/firestore');
const { getAuth } = require('firebase-admin/auth');
const { setGlobalOptions } = require('firebase-functions/v2');
// 注：Auth 触发器在 firebase-functions@5.x 只有 v1 API，
//     `v2/auth` 子路径不存在，会导致 ERR_PACKAGE_PATH_NOT_EXPORTED。
const functionsV1 = require('firebase-functions/v1');

initializeApp();
setGlobalOptions({ region: 'us-central1' });
const db = getFirestore();

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