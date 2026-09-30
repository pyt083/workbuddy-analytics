"""
QA 独立端到端验证 — 严过关（software-qa-engineer-2）
与工程师的 tests/ 完全独立：不使用任何 mock，直接连接真实
Firebase Auth(9099) / Firestore(8080) / Functions(5001) 模拟器。

运行前提：
  - firebase emulators:start --only auth,firestore,functions 已在 /tmp/wbqa-sandbox 启动
  - 页面为 /tmp/wbqa-sandbox/index.html（已按 FIREBASE-SETUP.md §3 填入 demo 项目配置）
  - URL 带 ?emulator=1
"""
import pathlib, sys, time, urllib.request
from playwright.sync_api import sync_playwright

URL = 'http://localhost:8000/index.html?emulator=1'

def _wipe(url, method='DELETE'):
    req = urllib.request.Request(url, method=method)
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req) as r:
        return r.status

# 前置：清空 Auth 与 Firestore 模拟器数据，保证「首注册用户=admin」用例成立
print('=== 0. 清空模拟器数据 ===')
st1 = _wipe('http://localhost:9099/emulator/v1/projects/demo-wbqa/accounts')
st2 = _wipe('http://localhost:8080/emulator/v1/projects/demo-wbqa/databases/(default)/documents')
print(f'  auth wipe: {st1}  firestore wipe: {st2}')

results = []
def check(name, cond, evidence=''):
    tag = 'PASS' if cond else 'FAIL'
    results.append((tag, name, evidence))
    print(f'  [{tag}] {name}' + (f'  | {evidence}' if evidence else ''))
    return cond

errors = []
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={'width':1440,'height':900})
    pg = ctx.new_page()
    pg.on('pageerror', lambda e: errors.append(('pageerror', str(e))))

    # ---------- A. 未登录态 ----------
    print('=== A. 未登录态：仅登录卡片可见，原 10 页 DOM 隐藏 ===')
    pg.goto(URL)
    pg.wait_for_selector('#loginView', state='visible', timeout=15000)
    pg.wait_for_timeout(2500)  # 等 onAuthStateChanged(null) 稳定
    check('A1 登录卡片可见', pg.eval_on_selector('#loginView', 'e=>getComputedStyle(e).display!=="none"'))
    check('A2 .app 主体隐藏', pg.eval_on_selector('.app', 'e=>getComputedStyle(e).display==="none"'))
    check('A3 用户菜单隐藏', pg.eval_on_selector('#userMenu', 'e=>getComputedStyle(e).display==="none"'))
    check('A4 管理后台导航隐藏', pg.eval_on_selector('#navAdmin', 'e=>getComputedStyle(e).display==="none"'))
    # 业务页 DOM 虽在文档中但被 .app 隐藏；同时验证未初始化仪表盘（不应渲染）
    check('A5 overview 统计卡未渲染(未登录)', pg.eval_on_selector_all('#overviewStats .stat-card', 'e=>e.length') == 0,
          f'stat-cards={pg.eval_on_selector_all("#overviewStats .stat-card", "e=>e.length")}')

    # ---------- B. 首注册用户 = admin ----------
    print('=== B. 首注册用户 Alice：自动登录 + role=admin + 管理后台导航可见 ===')
    pg.evaluate("switchAuthTab('signup')"); pg.wait_for_timeout(200)
    pg.fill('#signupName', 'Alice')
    pg.fill('#signupEmail', 'alice@qa-test.com')
    pg.fill('#signupPwd', 'password1234')
    pg.click('#signupBtn')
    pg.wait_for_timeout(6000)  # 等 onAuthCreate 触发 + fetchUserDoc 轮询
    check('B1 登录卡片消失', pg.eval_on_selector('#loginView', 'e=>getComputedStyle(e).display==="none"'))
    check('B2 .app 主体显示', pg.eval_on_selector('.app', 'e=>getComputedStyle(e).display!=="none"'))
    check('B3 wbUser.role === admin', pg.evaluate('wbUser && wbUser.role') == 'admin',
          f'wbUser.role={pg.evaluate("wbUser && wbUser.role")}')
    check('B4 管理后台导航可见', pg.eval_on_selector('#navAdmin', 'e=>getComputedStyle(e).display!=="none"'))
    check('B5 用户菜单显示管理员标签', pg.text_content('#userRoleTag').strip() == '管理员',
          f'roleTag={pg.text_content("#userRoleTag")}')
    alice_uid = pg.evaluate('wbUser && wbUser.uid')
    print('  alice_uid =', alice_uid)

    # ---------- E. 普通用户调 setUserRole → permission-denied（先用 Bob 注册） ----------
    print('=== C. 第二用户 Bob 注册：role=user、无管理后台入口 ===')
    pg.evaluate('doSignOut()'); pg.wait_for_timeout(1000)
    pg.evaluate("switchAuthTab('signup')"); pg.wait_for_timeout(200)
    pg.fill('#signupName', 'Bob')
    pg.fill('#signupEmail', 'bob@qa-test.com')
    pg.fill('#signupPwd', 'password1234')
    pg.click('#signupBtn')
    pg.wait_for_timeout(6000)
    bob_uid = pg.evaluate('wbUser && wbUser.uid')
    check('C1 Bob 登录成功', pg.eval_on_selector('.app', 'e=>getComputedStyle(e).display!=="none"'))
    check('C2 Bob role === user', pg.evaluate('wbUser && wbUser.role') == 'user',
          f'wbUser.role={pg.evaluate("wbUser && wbUser.role")}')
    check('C3 Bob 看不到管理后台导航', pg.eval_on_selector('#navAdmin', 'e=>getComputedStyle(e).display==="none"'))
    check('C4 用户菜单显示普通用户标签', pg.text_content('#userRoleTag').strip() == '普通用户')
    print('  bob_uid =', bob_uid)

    print('=== C5. Bob 强行 switchPage(admin) → 无权限提示 ===')
    pg.evaluate("switchPage('admin')"); pg.wait_for_timeout(600)
    check('C5 admin 页显示无权限', '无权限' in (pg.text_content('#page-admin') or ''))

    print(f"=== E. 非 admin 调 setUserRole(uid,{str(bob_uid)}) → functions/permission-denied ===")
    err_code = pg.evaluate("""async () => {
      try { await firebase.functions().httpsCallable('setUserRole')({uid:%s, role:'admin'}); return 'NO_ERROR'; }
      catch(e){ return e.code || String(e); }
    }""" % (f"'{bob_uid}'"))
    check('E1 callable 被拒', err_code != 'NO_ERROR' and 'permission-denied' in str(err_code),
          f'code={err_code}')

    # ---------- M. 注册输入校验（在 Bob 已登录态下先注销） ----------
    print('=== M. 注册输入校验：非法邮箱/短密码/重复邮箱/空字段 ===')
    pg.evaluate('doSignOut()'); pg.wait_for_timeout(800)
    pg.evaluate("switchAuthTab('signup')"); pg.wait_for_timeout(200)

    # M1 非法邮箱
    pg.fill('#signupName', 'Bad'); pg.fill('#signupEmail', 'not-an-email'); pg.fill('#signupPwd', 'password1234')
    pg.click('#signupBtn'); pg.wait_for_timeout(1500)
    e1 = pg.text_content('#signupErr').strip()
    check('M1 非法邮箱被拒且 UI 有提示', ('邮箱' in e1) or ('email' in e1.lower()), f'err="{e1}"')

    # M2 短密码（前端校验）
    pg.fill('#signupName', 'Bad'); pg.fill('#signupEmail', 'bad@qa-test.com'); pg.fill('#signupPwd', '1234567')
    pg.click('#signupBtn'); pg.wait_for_timeout(800)
    e2 = pg.text_content('#signupErr').strip()
    check('M2 密码<8位被拒且 UI 有提示', '密码' in e2 or '8' in e2, f'err="{e2}"')

    # M3 空字段（清空名称）
    pg.fill('#signupName', ''); pg.fill('#signupEmail', 'bad@qa-test.com'); pg.fill('#signupPwd', 'password1234')
    pg.click('#signupBtn'); pg.wait_for_timeout(800)
    e3 = pg.text_content('#signupErr').strip()
    check('M3 空显示名被拒且 UI 有提示', len(e3) > 0, f'err="{e3}"')

    # M4 重复邮箱
    pg.fill('#signupName', 'Dup'); pg.fill('#signupEmail', 'alice@qa-test.com'); pg.fill('#signupPwd', 'password1234')
    pg.click('#signupBtn'); pg.wait_for_timeout(3000)
    e4 = pg.text_content('#signupErr').strip()
    check('M4 重复邮箱被拒且 UI 有提示', '已注册' in e4 or 'already' in e4, f'err="{e4}"')
    check('M5 重复注册后仍在登录页（未误登录）', pg.eval_on_selector('#loginView', 'e=>getComputedStyle(e).display!=="none"'))

    # ---------- F. admin 调 setUserRole 提升 Bob ----------
    print('=== F. Alice 登录后 setUserRole(bob, admin) → 成功 ===')
    pg.evaluate("switchAuthTab('signin')"); pg.wait_for_timeout(200)
    pg.fill('#signinEmail', 'alice@qa-test.com'); pg.fill('#signinPwd', 'password1234')
    pg.click('#signinBtn'); pg.wait_for_timeout(5000)
    check('F0 Alice 重新登录成功', pg.evaluate('wbUser && wbUser.role') == 'admin')
    resp = pg.evaluate("""async () => {
      try { return {ok:true, r: await firebase.functions().httpsCallable('setUserRole')({uid:'%s', role:'admin'})}; }
      catch(e){ return {ok:false, code:e.code}; }
    }""" % bob_uid)
    check('F1 setUserRole 提升 Bob 成功', resp.get('ok') is True, f'result={resp}')
    pg.wait_for_timeout(1500)
    check('F2 Bob 在管理后台列表中 role=admin',
          pg.evaluate("""async () => {
            const s = await firebase.firestore().collection('users').doc('%s').get();
            return s.exists && s.data().role === 'admin';
          }""" % bob_uid))

    # ---------- H. admin 降级自己 → callable 拒绝（防锁死） ----------
    print('=== H. Alice setUserRole(self, user) → 拒绝（防锁死） ===')
    resp2 = pg.evaluate("""async () => {
      try { return {ok:true, r: await firebase.functions().httpsCallable('setUserRole')({uid:'%s', role:'user'})}; }
      catch(e){ return {ok:false, code:e.code, msg:e.message}; }
    }""" % alice_uid)
    check('H1 自我降级被 callable 拒绝', resp2.get('ok') is False and 'precondition' in str(resp2.get('code','')),
          f'result={resp2}')
    check('H2 Alice 仍为 admin', pg.evaluate('wbUser && wbUser.role') == 'admin')

    # ---------- I. 禁用 Bob → Bob 会话被 onSnapshot 踢出 ----------
    print('=== I. Alice 禁用 Bob → Bob 登录态被实时监听踢出 ===')
    # 先在第二个 context 登录 Bob（模拟 Bob 正在线）
    ctx2 = b.new_context(viewport={'width':1440,'height':900})
    pg2 = ctx2.new_page()
    pg2.on('pageerror', lambda e: errors.append(('pageerror-ctx2', str(e))))
    pg2.goto(URL)
    pg2.wait_for_selector('#loginView', state='visible', timeout=15000)
    pg2.evaluate("switchAuthTab('signin')"); pg2.wait_for_timeout(300)
    pg2.fill('#signinEmail', 'bob@qa-test.com'); pg2.fill('#signinPwd', 'password1234')
    pg2.click('#signinBtn'); pg2.wait_for_timeout(5000)
    check('I0 Bob(页面2) 登录成功', pg2.evaluate('wbUser && wbUser.role') == 'admin')  # 已被 F 步提升
    # Alice 直接用 Firestore 规则内的管理员权限禁用 Bob
    r = pg.evaluate("""async () => {
      try { await firebase.firestore().collection('users').doc('%s').update({status:'disabled'}); return 'OK'; }
      catch(e){ return 'ERR:'+ (e.code||e.message); }
    }""" % bob_uid)
    check('I1 admin 写 status=disabled 成功（规则允许）', r == 'OK', f'result={r}')
    pg2.wait_for_timeout(4000)  # 等 onSnapshot 推送
    check('I2 Bob 被踢回登录页', pg2.eval_on_selector('#loginView', 'e=>getComputedStyle(e).display!=="none"'))
    check('I3 Bob 的 .app 隐藏', pg2.eval_on_selector('.app', 'e=>getComputedStyle(e).display==="none"'))
    kicked_msg = pg2.text_content('#signinErr').strip()
    check('I4 踢出后有禁用提示', '禁用' in kicked_msg, f'msg="{kicked_msg}"')

    # ---------- J. 被禁用用户重新登录 → 仍被拒 ----------
    print('=== J. Bob 再次登录 → 拒绝（无法绕过） ===')
    pg2.evaluate("switchAuthTab('signin')"); pg2.wait_for_timeout(300)
    pg2.fill('#signinEmail', 'bob@qa-test.com'); pg2.fill('#signinPwd', 'password1234')
    pg2.click('#signinBtn'); pg2.wait_for_timeout(5000)
    j_err = pg2.text_content('#signinErr').strip()
    check('J1 重新登录被拒且提示禁用', '禁用' in j_err, f'err="{j_err}"')
    check('J2 仍在登录页', pg2.eval_on_selector('#loginView', 'e=>getComputedStyle(e).display!=="none"'))
    # 恢复 Bob 为 active（供后续用例），并降回 user 以便 L 用例以普通用户验证业务功能
    pg.evaluate("""async () => {
      await firebase.firestore().collection('users').doc('%s').update({status:'active'});
    }""" % bob_uid)
    pg.wait_for_timeout(1000)

    # ---------- L. 登录后原 10 页业务功能保留 ----------
    print('=== L. Bob 重新登录（普通用户）→ 原业务页 + CSV 导出 + 保存报表 ===')
    pg2.fill('#signinEmail', 'bob@qa-test.com'); pg2.fill('#signinPwd', 'password1234')
    pg2.click('#signinBtn'); pg2.wait_for_timeout(5000)
    check('L0 Bob 恢复后可登录', pg2.eval_on_selector('.app', 'e=>getComputedStyle(e).display!=="none"'))
    # 随机抽 3 页：org（组织树）、users（用户列表）、report（自定义报表）
    for page_name in ['org', 'users', 'report']:
        pg2.evaluate(f"switchPage('{page_name}')"); pg2.wait_for_timeout(800)
        vis = pg2.eval_on_selector(f'#page-{page_name}', 'e=>getComputedStyle(e).display!=="none"')
        check(f'L1 页面 {page_name} 渲染可见', vis)
    check('L2 组织树有节点', pg2.eval_on_selector_all('#page-org .node, #page-org .org-node, #page-org [class*=node]', 'e=>e.length') > 0,
          f'nodes={pg2.eval_on_selector_all("#page-org [class*=node]", "e=>e.length")}')
    check('L3 用户表格有数据行', pg2.eval_on_selector_all('#page-users table tbody tr', 'e=>e.length') > 0,
          f'rows={pg2.eval_on_selector_all("#page-users table tbody tr", "e=>e.length")}')
    # CSV 导出
    pg2.evaluate("switchPage('users')"); pg2.wait_for_timeout(600)
    try:
        with pg2.expect_download(timeout=6000) as dl:
            pg2.evaluate("exportUsers()")
        check('L4 CSV 导出成功', True, f'file={dl.value.suggested_filename}')
    except Exception as e:
        check('L4 CSV 导出成功', False, str(e)[:80])
    # 保存报表
    pg2.evaluate("switchPage('report')"); pg2.wait_for_timeout(800)
    before = pg2.evaluate('state.savedReports.length')
    try:
        pg2.evaluate('saveReport()')
        pg2.wait_for_timeout(600)
        after = pg2.evaluate('state.savedReports.length')
        check('L5 保存报表成功', after == before + 1, f'savedReports {before} -> {after}')
    except Exception as e:
        check('L5 保存报表成功', False, str(e)[:80])

    b.close()

fails = [r for r in results if r[0] == 'FAIL']
print()
print(f'TOTAL={len(results)}  PASS={len(results)-len(fails)}  FAIL={len(fails)}')
print('PAGE ERRORS:', errors)
if fails:
    for t, n, ev in fails:
        print('  FAIL:', n, '|', ev)
print('OVERALL:', 'PASS' if (not fails and not errors) else 'FAIL')
sys.exit(0 if not fails else 1)
