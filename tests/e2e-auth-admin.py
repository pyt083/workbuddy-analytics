"""
WorkBuddy 数据分析平台 — Firebase 登录/管理后台端到端验证

- 用 Playwright 加载页面（file:// URL）
- 通过 page.add_init_script 注入 mock-firebase.js 替换 window.firebase
- 阻断真实的 gstatic.com Firebase SDK 加载，确保 mock 生效
- 验证：
   1) 未登录只显示登录卡片，原 10 页被隐藏
   2) 首注册用户自动管理员（role='admin'），侧边导航出现「管理 / 管理后台」
   3) 第二个用户自动普通（role='user'），无管理后台入口；强行访问被拒绝
   4) 管理员可看用户列表、提权、降级、禁用，防锁死（自己不可降级/禁用）
   5) 当前登录用户被「另一管理员」禁用 → 实时快照监听 → 自动登出 → 显示登录卡片
   6) 原业务功能（10 页 + 筛选 + 导出）登录后一切正常
"""

from playwright.sync_api import sync_playwright
import glob, os, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent  # 仓库根目录

# Chromium 启动兜底：优先用 playwright 自带安装；不可用时（下载受限）复用本机缓存版本
def _cached_chromium():
    pats = [
        os.path.expanduser('~/Library/Caches/ms-playwright/chromium-*/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'),
        os.path.expanduser('~/.cache/ms-playwright/chromium-*/chrome-linux/chrome'),
    ]
    for pat in pats:
        hits = sorted(glob.glob(pat), reverse=True)
        if hits: return hits[0]
    return None

def launch_chromium(p):
    try:
        return p.chromium.launch()
    except Exception:
        exe = _cached_chromium()
        if not exe: raise
        print('  [INFO] 使用本机缓存 Chromium:', exe)
        return p.chromium.launch(executable_path=exe)

errors, console_errs = [], []

with sync_playwright() as p:
    b = launch_chromium(p)
    ctx = b.new_context(viewport={'width':1440,'height':900})
    # 仅阻断 Firebase CDN（让 mock 接管），其它 CDN（如 jsdelivr ECharts）正常加载
    def maybe_abort(route, request):
        url = request.url
        if 'gstatic.com' in url or 'firebaseio.com' in url:
            route.abort()
        else:
            route.continue_()
    ctx.route('**/*', maybe_abort)
    # 注入 mock 在所有脚本之前
    with open(os.path.join(ROOT, 'tests/firebase-mock.js'), encoding='utf-8') as f:
        ctx.add_init_script(f.read())

    pg = ctx.new_page()
    pg.on('pageerror', lambda e: errors.append(('pageerror', str(e))))
    # console.err 列表仅收集「非网络资源加载错误」（被我们主动 abort 的 Firebase SDK 不算代码错误）
    def on_console(m):
        if m.type != 'error':
            return
        text = m.text
        if 'ERR_FAILED' in text or 'Failed to load resource' in text or 'gstatic' in text or 'firebaseio' in text:
            return
        console_errs.append(text)
    pg.on('console', on_console)

    URL = (ROOT / 'index.html').as_uri()
    pg.goto(URL)
    pg.wait_for_timeout(2500)

    def assert_true(name, cond):
        print(f'  [{ "PASS" if cond else "FAIL" }] {name}')
        if not cond: errors.append(('assert', name))
        return cond

    print('=== 1) 未登录态 ===')
    assert_true('login view visible',     pg.eval_on_selector('#loginView', 'e=>getComputedStyle(e).display!=="none"'))
    assert_true('app hidden',            pg.eval_on_selector('.app',      'e=>getComputedStyle(e).display==="none"'))
    assert_true('user menu hidden',      pg.eval_on_selector('#userMenu', 'e=>getComputedStyle(e).display==="none"'))
    assert_true('admin nav hidden',      pg.eval_on_selector('#navAdmin', 'e=>getComputedStyle(e).display==="none"'))

    print('=== 2) 注册首位用户 Alice（自动管理员）===')
    pg.evaluate("switchAuthTab('signup')"); pg.wait_for_timeout(200)
    pg.fill('#signupName', 'Alice')
    pg.fill('#signupEmail', 'alice@test.com')
    pg.fill('#signupPwd',   'password1234')
    pg.click('#signupBtn')
    pg.wait_for_timeout(2500)
    alice_uid = pg.evaluate("(()=>{const u=__WB_FAKE__.users;return Object.keys(u).find(k=>u[k].email==='alice@test.com');})()")
    print('  alice uid:', alice_uid)
    assert_true('alice user doc exists', alice_uid is not None)
    assert_true('alice role = admin',    pg.evaluate(f"__WB_FAKE__.users['{alice_uid}'].role") == 'admin')
    assert_true('dashboard shown',       pg.eval_on_selector('.app',      'e=>getComputedStyle(e).display!=="none"'))
    assert_true('user menu shown',       pg.eval_on_selector('#userMenu', 'e=>getComputedStyle(e).display!=="none"'))
    assert_true('user is admin',         pg.evaluate('wbUser.role') == 'admin')
    assert_true('admin nav visible',     pg.eval_on_selector('#navAdmin', 'e=>getComputedStyle(e).display!=="none"'))
    assert_true('admin group visible',   pg.eval_on_selector('#navAdminGroup', 'e=>getComputedStyle(e).display!=="none"'))
    assert_true('overview stat cards',   pg.eval_on_selector_all('#overviewStats .stat-card', 'e=>e.length') == 6)

    print('=== 3) Alice 进入管理后台，列出自己一行；自我禁用按钮 disabled ===')
    pg.evaluate("switchPage('admin')"); pg.wait_for_timeout(1200)
    assert_true('admin rows = 1',        pg.eval_on_selector_all('#adminTbody tr', 'e=>e.length') == 1)
    assert_true('self-action disabled',  pg.eval_on_selector_all('#adminTbody button[disabled]', 'e=>e.length') >= 1)
    assert_true('no promote btn on self', pg.eval_on_selector_all('#adminTbody button', 'e=>Array.from(e).filter(b=>b.textContent.includes("提升为管理员")).length') == 0)

    print('=== 4) 注销，注册第二位用户 Bob（role=user）===')
    pg.evaluate("doSignOut()"); pg.wait_for_timeout(700)
    assert_true('login view after signout', pg.eval_on_selector('#loginView','e=>getComputedStyle(e).display!=="none"'))

    pg.evaluate("switchAuthTab('signup')"); pg.wait_for_timeout(200)
    pg.fill('#signupName','Bob'); pg.fill('#signupEmail','bob@test.com'); pg.fill('#signupPwd','password1234')
    pg.click('#signupBtn'); pg.wait_for_timeout(2500)
    bob_uid = pg.evaluate("(()=>{const u=__WB_FAKE__.users;return Object.keys(u).find(k=>u[k].email==='bob@test.com');})()")
    print('  bob uid:', bob_uid)
    assert_true('bob user doc exists',  bob_uid is not None)
    assert_true('bob role = user',      pg.evaluate(f"__WB_FAKE__.users['{bob_uid}'].role") == 'user')
    assert_true('admin nav HIDDEN (Bob)', pg.eval_on_selector('#navAdmin', 'e=>getComputedStyle(e).display==="none"'))

    print('=== 5) Bob 强行访问 admin 页面 → 显示无权限 ===')
    pg.evaluate("switchPage('admin')"); pg.wait_for_timeout(500)
    denied_text = pg.text_content('#page-admin')
    assert_true('admin page shows denial', '无权限' in denied_text)

    print('=== 6) Bob 调 setUserRole → functions/permission-denied ===')
    try:
        pg.evaluate("firebase.functions().httpsCallable('setUserRole')({uid:'x',role:'admin'})")
        print('  [FAIL] non-admin callable should reject')
        errors.append(('assert','non-admin callable rejected'))
    except Exception as e:
        print('  [PASS] non-admin callable rejected:', str(e)[:80])

    print('=== 7) 注销 Bob，登录 Alice，把 Bob 提升为管理员 ===')
    pg.evaluate("doSignOut()"); pg.wait_for_timeout(700)
    pg.evaluate("switchAuthTab('signin')"); pg.wait_for_timeout(200)
    pg.fill('#signinEmail','alice@test.com'); pg.fill('#signinPwd','password1234')
    pg.click('#signinBtn'); pg.wait_for_timeout(2500)
    pg.evaluate("switchPage('admin')"); pg.wait_for_timeout(1200)
    assert_true('admin rows = 2', pg.eval_on_selector_all('#adminTbody tr','e=>e.length') == 2)
    pg.evaluate(f"doAdminRole('{bob_uid}','admin')"); pg.wait_for_timeout(800)
    assert_true('bob promoted',  pg.evaluate(f"__WB_FAKE__.users['{bob_uid}'].role") == 'admin')

    print('=== 8) Alice 试图降级自己 → blocked（防锁死，alert 后直接 return，无异常）===')
    # 页面用 alert 阻断然后 return，不会抛出异常。我们这里直接看 wbUser 是否仍是 admin。
    pg.evaluate(f"doAdminRole('{alice_uid}','user')")  # 会触发 alert（headless 中忽略）
    pg.wait_for_timeout(300)
    assert_true('alice still admin (no self-demote)', pg.evaluate('wbUser.role') == 'admin')
    assert_true('mock store: alice role unchanged',     pg.evaluate(f"__WB_FAKE__.users['{alice_uid}'].role") == 'admin')

    print('=== 9) 禁用模拟：__WB_FAKE__.setUserStatus(alice,"disabled") 触发实时监听 → Alice 被踢出 ===')
    pg.evaluate(f"__WB_FAKE__.setUserStatus('{alice_uid}','disabled')"); pg.wait_for_timeout(2000)
    assert_true('after disable, login visible', pg.eval_on_selector('#loginView','e=>getComputedStyle(e).display!=="none"'))
    assert_true('after disable, app hidden',    pg.eval_on_selector('.app','e=>getComputedStyle(e).display==="none"'))
    assert_true('after disable, currentUser null', pg.evaluate('__WB_FAKE__.users["'+alice_uid+'"].status==="disabled"') and pg.evaluate('window.__wbUser') in (None,'null'))

    print('=== 10) Alice 重新登录被拒绝（user-disabled）===')
    pg.evaluate("switchAuthTab('signin')"); pg.wait_for_timeout(200)
    pg.fill('#signinEmail','alice@test.com'); pg.fill('#signinPwd','password1234')
    pg.click('#signinBtn'); pg.wait_for_timeout(1500)
    err_text = pg.text_content('#signinErr')
    assert_true('signin rejected when disabled', '已被禁用' in err_text or 'disabled' in err_text)

    print('=== 11) 登录 Bob（现在是 admin）→ 走完原 10 页 + 导出 CSV ===')
    pg.fill('#signinEmail','bob@test.com'); pg.click('#signinBtn'); pg.wait_for_timeout(2500)
    pg.evaluate("switchPage('overview')"); pg.wait_for_timeout(500)
    assert_true('overview stat cards after bob login', pg.eval_on_selector_all('#overviewStats .stat-card','e=>e.length') == 6)
    for page_name in ['org','users','tasks','category','position','prompt','dialogue','upload','report']:
        pg.evaluate(f"switchPage('{page_name}')"); pg.wait_for_timeout(450)
    print('  [PASS] 遍历 10 个原页面 + 1 个 admin 页面无报错')

    # 导出 CSV
    pg.evaluate("switchPage('users')"); pg.wait_for_timeout(500)
    try:
        with pg.expect_download(timeout=4000) as dl:
            pg.evaluate("exportUsers()")
        print('  [PASS] 导出 CSV:', dl.value.suggested_filename)
    except Exception as e:
        print('  [FAIL] exportUsers:', e)
        errors.append(('export','exportUsers'))

    pg.evaluate("switchPage('admin')"); pg.wait_for_timeout(500)
    print('  [INFO] admin rows =', pg.eval_on_selector_all('#adminTbody tr','e=>e.length'))

    # ================= WorkBuddy 数据源（真实 Open API mock 路径）=================
    print('=== 12) 未授权态点「我的 WorkBuddy 数据」→ 引导卡片 + 回退 Mock ===')
    pg.evaluate("__WB_FAKE__.wbState.mode='noauth'")
    mock_task_count = pg.evaluate('TASKS.length')
    assert_true('mock 数据量 > 100（基线）', mock_task_count > 100)
    pg.evaluate("switchPage('overview')"); pg.wait_for_timeout(300)
    pg.click('#dsOptReal'); pg.wait_for_timeout(1200)
    assert_true('回退 Mock（DATA.source=mock）', pg.evaluate("DATA.source") == 'mock')
    assert_true('引导卡片出现', pg.eval_on_selector('#apiGuideCard','e=>getComputedStyle(e).display!=="none"'))
    assert_true('去授权按钮可见', pg.eval_on_selector('#wbAuthBtn','e=>getComputedStyle(e).display!=="none"'))
    assert_true('引导卡片错误提示非空', len(pg.text_content('#wbGuideErr').strip()) > 0)
    assert_true('数据源偏好回写 mock', pg.evaluate("localStorage.getItem('wb_data_source')") == 'mock')

    print('=== 13) 已授权态：切换到真实数据源 ===')
    pg.evaluate("__WB_FAKE__.wbState.mode='ok'")
    pg.click('#dsOptReal'); pg.wait_for_timeout(1500)
    assert_true('DATA.source=api', pg.evaluate("DATA.source") == 'api')
    assert_true('任务数 = mock 提供的 8 条', pg.evaluate('TASKS.length') == 8)
    assert_true('切换器高亮 real', 'active' in (pg.get_attribute('#dsOptReal','class') or ''))
    assert_true('引导卡片显示已连接', '已连接' in (pg.text_content('#wbConnectedBody') or ''))
    assert_true('用户=授权账号（部门）', pg.evaluate("USERS[0].dept") == '授权账号')
    assert_true('昵称=WorkBuddy测试账号', pg.evaluate("USERS[0].name") == 'WorkBuddy测试账号')
    assert_true('classifyTaskName 生效（验收报告→文档写作）', pg.evaluate("TASKS[0].category") == '文档写作')
    assert_true('classifyTaskName 生效（可视化分析→数据分析）', pg.evaluate("TASKS[1].category") == '数据分析')
    assert_true('API 任务状态映射（completed→已完成）', pg.evaluate("TASKS[0].status") == '已完成')
    assert_true('rounds/outCount/upCount 置 0', pg.evaluate("TASKS.every(t=>t.rounds===0&&t.outCount===0&&t.upCount===0)"))
    # 时间筛选对真实数据生效
    pg.evaluate("applyRange('90d')"); pg.wait_for_timeout(300)
    assert_true('近90天筛选后仍 8 条', pg.evaluate('getFilteredTasks().length') == 8)
    # 任务明细页显示真实任务 + 「API 暂未开放」提示条
    pg.evaluate("switchPage('tasks')"); pg.wait_for_timeout(400)
    task_text = pg.text_content('#taskTbody')
    assert_true('任务表含真实任务 ID', 'wb_1000' in task_text)
    assert_true('任务表含真实任务标题', '起草一份项目验收报告' in task_text)
    # 提示词页：API 暂未开放提示条
    pg.evaluate("switchPage('prompt')"); pg.wait_for_timeout(400)
    assert_true('prompt 页 API 提示条可见', pg.eval_on_selector('#apiNotePrompt','e=>getComputedStyle(e).display!=="none"'))
    pg.evaluate("switchPage('dialogue')"); pg.wait_for_timeout(300)
    assert_true('dialogue 页 API 提示条可见', pg.eval_on_selector('#apiNoteDialogue','e=>getComputedStyle(e).display!=="none"'))
    pg.evaluate("switchPage('upload')"); pg.wait_for_timeout(300)
    assert_true('upload 页 API 提示条可见', pg.eval_on_selector('#apiNoteUpload','e=>getComputedStyle(e).display!=="none"'))
    # 对话占位
    assert_true('dialogOf 返回占位文案', '暂未开放' in pg.evaluate("dialogOf(TASKS[0]).map(d=>d.text).join(' ')"))
    # 真实数据下导出 CSV
    pg.evaluate("switchPage('users')"); pg.wait_for_timeout(400)
    try:
        with pg.expect_download(timeout=4000) as dl2:
            pg.evaluate("exportUsers()")
        print('  [PASS] 真实数据源导出 CSV:', dl2.value.suggested_filename)
    except Exception as e:
        print('  [FAIL] exportUsers(api):', e)
        errors.append(('export','exportUsers(api)'))
    assert_true('数据源偏好 = real', pg.evaluate("localStorage.getItem('wb_data_source')") == 'real')

    print('=== 14) 切回演示数据 → Mock 完整恢复 ===')
    pg.click('#dsOptMock'); pg.wait_for_timeout(800)
    assert_true('DATA.source=mock', pg.evaluate("DATA.source") == 'mock')
    assert_true('任务数恢复 Mock 基线', pg.evaluate('TASKS.length') == mock_task_count)
    assert_true('API 提示条隐藏', pg.eval_on_selector('#apiNotePrompt','e=>getComputedStyle(e).display==="none"'))
    assert_true('数据源偏好 = mock', pg.evaluate("localStorage.getItem('wb_data_source')") == 'mock')

    print('=== 15) 真实源下注销 → 自动回退 Mock；回调页防护 ===')
    pg.click('#dsOptReal'); pg.wait_for_timeout(1200)
    assert_true('回到真实源', pg.evaluate("DATA.source") == 'api')
    pg.evaluate("doSignOut()"); pg.wait_for_timeout(900)
    assert_true('注销后回退 Mock', pg.evaluate("DATA.source") == 'mock')
    assert_true('注销后回登录页', pg.eval_on_selector('#loginView','e=>getComputedStyle(e).display!=="none"'))

    # oauth/callback/index.html：无 code / state 不匹配 两条防护路径（file:// 下 mock 已注入）
    cb_uri = (ROOT / 'oauth/callback/index.html').as_uri()
    cb1 = ctx.new_page()
    cb1.on('pageerror', lambda e: errors.append(('cb-pageerror', str(e))))
    def on_console_cb(m):
        if m.type != 'error': return
        t = m.text
        if 'ERR_FAILED' in t or 'Failed to load resource' in t or 'gstatic' in t or 'firebaseio' in t: return
        console_errs.append('[callback] '+t)
    cb1.on('console', on_console_cb)
    cb1.goto(cb_uri); cb1.wait_for_timeout(800)
    assert_true('回调页：无 code → 提示缺少授权码', '缺少授权码' in (cb1.text_content('#main') or ''))
    cb1.goto(cb_uri + '?code=abc123&state=xyz'); cb1.wait_for_timeout(800)
    assert_true('回调页：state 不匹配 → 校验失败', 'state 校验失败' in (cb1.text_content('#main') or ''))
    assert_true('回调页：展示重新授权/返回按钮', cb1.eval_on_selector('#actions','e=>getComputedStyle(e).display!=="none"'))
    cb1.close()

    b.close()

print()
print('PAGE ERRORS:', errors)
print('CONSOLE ERRORS:', console_errs)
print('OVERALL:', 'PASS' if (not errors and not console_errs) else 'FAIL')