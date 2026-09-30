/**
 * QA 独立 Firestore 安全规则单元测试 — 严过关（software-qa-engineer-2）
 * 覆盖任务要求的 4 个关键场景 + 补充边界。
 * 运行：node rules.test.js（需 Firestore 模拟器已在 8080 端口运行）
 */
const { initializeTestEnvironment, assertFails, assertSucceeds } = require('@firebase/rules-unit-testing');
const { readFileSync } = require('fs');

const PROJECT_ID = 'demo-wbqa-rules';
let testEnv;

const results = [];
function check(name, ok, evidence) {
  results.push({ name, ok, evidence: evidence || '' });
  console.log(`  [${ok ? 'PASS' : 'FAIL'}] ${name}${evidence ? '  | ' + evidence : ''}`);
}

beforeAll = async () => {
  testEnv = await initializeTestEnvironment({
    projectId: PROJECT_ID,
    firestore: { rules: readFileSync('/tmp/wbqa-sandbox/firestore.rules', 'utf8') },
  });
  // 种子数据：绕过规则写入两个用户档案
  await testEnv.withSecurityRulesDisabled(async (ctx) => {
    const db = ctx.firestore();
    await db.collection('users').doc('admin1').set({
      uid: 'admin1', email: 'admin@qa.com', displayName: 'Admin',
      role: 'admin', status: 'active', createdAt: new Date(),
    });
    await db.collection('users').doc('user1').set({
      uid: 'user1', email: 'user@qa.com', displayName: 'User',
      role: 'user', status: 'active', createdAt: new Date(),
    });
  });
};

async function main() {
  await beforeAll();

  // R1. 普通用户尝试写自己的 role → deny
  {
    const db = testEnv.authenticatedContext('user1').firestore();
    let ok = true, ev = '';
    try { await assertFails(db.doc('users/user1').update({ role: 'admin' })); }
    catch (e) { ok = false; ev = e.message.slice(0, 100); }
    check('R1 普通用户改自己 role → deny', ok, ev);
  }

  // R1b. 普通用户尝试写自己的 status → deny
  {
    const db = testEnv.authenticatedContext('user1').firestore();
    let ok = true, ev = '';
    try { await assertFails(db.doc('users/user1').update({ status: 'disabled' })); }
    catch (e) { ok = false; ev = e.message.slice(0, 100); }
    check('R1b 普通用户改自己 status → deny', ok, ev);
  }

  // R2. 普通用户读别人的 user doc → deny
  {
    const db = testEnv.authenticatedContext('user1').firestore();
    let ok = true, ev = '';
    try { await assertFails(db.doc('users/admin1').get()); }
    catch (e) { ok = false; ev = e.message.slice(0, 100); }
    check('R2 普通用户读他人 user doc → deny', ok, ev);
  }

  // R2b. 普通用户读自己的 doc → allow（对照）
  {
    const db = testEnv.authenticatedContext('user1').firestore();
    let ok = true, ev = '';
    try { await assertSucceeds(db.doc('users/user1').get()); }
    catch (e) { ok = false; ev = e.message.slice(0, 100); }
    check('R2b 用户读自己的 doc → allow（对照）', ok, ev);
  }

  // R3. admin 写任何 user 的 role / status → allow
  {
    const db = testEnv.authenticatedContext('admin1').firestore();
    let ok = true, ev = '';
    try {
      await assertSucceeds(db.doc('users/user1').update({ role: 'admin' }));
      await assertSucceeds(db.doc('users/user1').update({ status: 'disabled' }));
    } catch (e) { ok = false; ev = e.message.slice(0, 100); }
    check('R3 admin 写 role + status → allow', ok, ev);
    // 恢复
    await db.doc('users/user1').update({ role: 'user', status: 'active' });
  }

  // R4. 任何人（登录/未登录）直接 create /users/xxx（绕过 Functions）→ deny（关键！）
  {
    const authed = testEnv.authenticatedContext('user1').firestore();
    let ok = true, ev = '';
    try {
      await assertFails(authed.doc('users/user1-selfcreate').set({
        uid: 'user1-selfcreate', role: 'admin', status: 'active', email: 'x@x.com',
      }));
    } catch (e) { ok = false; ev = 'authed: ' + e.message.slice(0, 80); }
    check('R4a 登录用户直接 create users doc → deny（关键）', ok, ev);
  }
  {
    const unauthed = testEnv.unauthenticatedContext().firestore();
    let ok = true, ev = '';
    try {
      await assertFails(unauthed.doc('users/ghost').set({ uid: 'ghost', role: 'admin' }));
    } catch (e) { ok = false; ev = e.message.slice(0, 80); }
    check('R4b 未登录直接 create users doc → deny', ok, ev);
  }

  // R5. 未登录读任何 users doc → deny
  {
    const db = testEnv.unauthenticatedContext().firestore();
    let ok = true, ev = '';
    try { await assertFails(db.doc('users/user1').get()); }
    catch (e) { ok = false; ev = e.message.slice(0, 80); }
    check('R5 未登录读 user doc → deny', ok, ev);
  }

  // R6. 用户改自己的 displayName → allow（对照：合法自助操作）
  {
    const db = testEnv.authenticatedContext('user1').firestore();
    let ok = true, ev = '';
    try { await assertSucceeds(db.doc('users/user1').update({ displayName: 'NewName' })); }
    catch (e) { ok = false; ev = e.message.slice(0, 80); }
    check('R6 用户改自己 displayName → allow（对照）', ok, ev);
  }

  // R7. admin 尝试改 email（不在允许字段内）→ deny
  {
    const db = testEnv.authenticatedContext('admin1').firestore();
    let ok = true, ev = '';
    try { await assertFails(db.doc('users/user1').update({ email: 'hacked@x.com' })); }
    catch (e) { ok = false; ev = e.message.slice(0, 80); }
    check('R7 admin 改 email（越权字段）→ deny', ok, ev);
  }

  // R8. 用户改别人的 displayName → deny
  {
    const db = testEnv.authenticatedContext('user1').firestore();
    let ok = true, ev = '';
    try { await assertFails(db.doc('users/admin1').update({ displayName: 'Hijack' })); }
    catch (e) { ok = false; ev = e.message.slice(0, 80); }
    check('R8 用户改他人 displayName → deny', ok, ev);
  }

  // R9. delete users doc → deny（任何人）
  {
    const db = testEnv.authenticatedContext('admin1').firestore();
    let ok = true, ev = '';
    try { await assertFails(db.doc('users/user1').delete()); }
    catch (e) { ok = false; ev = e.message.slice(0, 80); }
    check('R9 admin 删除 user doc → deny', ok, ev);
  }

  // R10. 其它集合（如伪造 reports）读写 → deny（默认拒绝）
  {
    const db = testEnv.authenticatedContext('user1').firestore();
    let ok = true, ev = '';
    try {
      await assertFails(db.collection('reports').add({ a: 1 }));
      await assertFails(db.doc('reports/x').get());
    } catch (e) { ok = false; ev = e.message.slice(0, 80); }
    check('R10 未定义集合（reports）读/写 → deny', ok, ev);
  }

  await testEnv.cleanup();
  const fails = results.filter(r => !r.ok);
  console.log(`\nTOTAL=${results.length}  PASS=${results.length - fails.length}  FAIL=${fails.length}`);
  console.log('OVERALL:', fails.length ? 'FAIL' : 'PASS');
  process.exit(fails.length ? 1 : 0);
}

main().catch(e => { console.error('FATAL', e); process.exit(2); });
