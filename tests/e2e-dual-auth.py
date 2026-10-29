"""
WorkBuddy 数据分析平台 — 双轨鉴权 + 预置演示管理员账号 端到端验证

真跑 Playwright（headless Chromium），两个站点由本地 python3 -m http.server 提供：

站点 A（仓库原样，__WB_FIREBASE_CONFIG__ 仍为占位符 → 判定 local 演示模式）
  A1  首屏：登录卡片可见 / 演示模式横幅 / 无白屏 / authMode==='local'
  A2  预置演示管理员种子：wb_local_accounts 自动写入 admin@workbuddy.local
      （role=admin、SHA-256 加盐、无明文口令）；登录页展示凭据卡与风险提示
  A3  「一键填入并登录」→ 进入看板，role=admin，管理后台入口可见
  A4  刷新保持登录
  A5  种子账号在线时注册第二个账号 → role=user，管理入口隐藏，强闯无权限
  A6  报错用例：邮箱格式 / 密码 <8 位 / 邮箱重复 / 密码错误
  A7  管理员提权 / 禁用 / 启用；被禁账号登录被拒
  A8  防锁死：管理员不能降级/禁用自己
  A9  跨标签页在线踢出
  A10 业务回归：10 页 + 时间筛选 + CSV 导出 + 保存自定义报表
  A11 真实数据源在演示模式下置灰且点击被拦截
  A12 重置：清空演示账号 → 刷新后种子再次生成；不刷新直接注册则首个账号为管理员

站点 B（假但格式合法的 Firebase 配置 → 判定 firebase 云端模式）
  B1  SDK 未加载 → 友好错误卡片（非白屏）+ 不创建种子账号
  B2  SDK 存在但初始化抛错 → 友好错误卡片（非白屏）
  B3  点「改用演示模式」→ 立刻可注册登录（降级闭环）

用法： python3 tests/e2e-dual-auth.py
"""

import glob
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
TMP_SITE = ROOT / '.tmp-e2e-fakesite'
ECHARTS_CACHE = ROOT / '.tmp-e2e-cache' / 'echarts.min.js'

SEED_EMAIL = 'admin@workbuddy.local'
SEED_PWD = 'WorkBuddy@2026'

FAKE_CFG = (
    'apiKey:"AIzaSyDUMMYKEYFORTESTINGONLY0123456789"',
    'authDomain:"demo-wb-project.firebaseapp.com"',
    'projectId:"demo-wb-project"',
    'storageBucket:"demo-wb-project.appspot.com"',
    'messagingSenderId:"000000000000"',
    'appId:"1:000000000000:web:abcdef1234567890"',
)

errors, console_errs, dialogs = [], [], []


# ---------------------------------------------------------------- 工具函数
def _cached_chromium():
    pats = [
        os.path.expanduser('~/Library/Caches/ms-playwright/chromium-*/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'),
        os.path.expanduser('~/.cache/ms-playwright/chromium-*/chrome-linux/chrome'),
    ]
    for pat in pats:
        hits = sorted(glob.glob(pat), reverse=True)
        if hits:
            return hits[0]
    return None


def launch_chromium(p):
    try:
        return p.chromium.launch()
    except Exception:
        exe = _cached_chromium()
        if not exe:
            raise
        print('  [INFO] 使用本机缓存 Chromium:', exe)
        return p.chromium.launch(executable_path=exe)


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def start_server(directory, port):
    proc = subprocess.Popen(
        [sys.executable, '-m', 'http.server', str(port), '--directory', str(directory)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    url = f'http://127.0.0.1:{port}/index.html'
    for _ in range(60):
        try:
            urllib.request.urlopen(url, timeout=1).read(16)
            return proc, url
        except Exception:
            time.sleep(0.15)
    proc.kill()
    raise RuntimeError(f'本地 http.server 启动失败: {url}')


def ensure_echarts_cache():
    """把 ECharts CDN 拉到本地缓存，避免测试因外网抖动（load 事件悬挂）而假失败。"""
    if ECHARTS_CACHE.is_file() and ECHARTS_CACHE.stat().st_size > 200000:
        return ECHARTS_CACHE
    ECHARTS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    try:
        req = urllib.request.Request(
            'https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js',
            headers={'User-Agent': 'Mozilla/5.0'},
        )
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = resp.read()
        ECHARTS_CACHE.write_bytes(data)
        print(f'  [INFO] ECharts 已缓存 ({len(data)} bytes)')
        return ECHARTS_CACHE
    except Exception as e:
        print('  [WARN] ECharts 缓存失败，将阻断该 CDN:', e)
        return None


def build_fake_site():
    """生成一个「假但格式合法」的 Firebase 配置副本站点。"""
    if TMP_SITE.exists():
        shutil.rmtree(TMP_SITE)
    TMP_SITE.mkdir(parents=True)
    html = (ROOT / 'index.html').read_text(encoding='utf-8')
    for old, new in (
        ('apiKey:"YOUR_API_KEY"', FAKE_CFG[0]),
        ('authDomain:"YOUR_PROJECT_ID.firebaseapp.com"', FAKE_CFG[1]),
        ('projectId:"YOUR_PROJECT_ID"', FAKE_CFG[2]),
        ('storageBucket:"YOUR_PROJECT_ID.appspot.com"', FAKE_CFG[3]),
        ('messagingSenderId:"YOUR_SENDER_ID"', FAKE_CFG[4]),
        ('appId:"YOUR_APP_ID"', FAKE_CFG[5]),
    ):
        if old not in html:
            raise RuntimeError(f'index.html 中未找到占位配置片段: {old}')
        html = html.replace(old, new)
    (TMP_SITE / 'index.html').write_text(html, encoding='utf-8')
    return TMP_SITE


def make_router(echarts_cache):
    """阻断 Firebase CDN；ECharts 用本地缓存兑现（保证 load 事件稳定）。"""
    def router(route, request):
        url = request.url
        if 'gstatic.com' in url or 'firebaseio.com' in url:
            route.abort()
        elif 'echarts' in url and echarts_cache:
            route.fulfill(path=str(echarts_cache),
                          headers={'content-type': 'application/javascript'})
        else:
            route.continue_()
    return router


# ---------------------------------------------------------------- 断言
def assert_true(name, cond, extra=''):
    print(f'  [{"PASS" if cond else "FAIL"}] {name}{(" | " + str(extra)) if extra else ""}')
    if not cond:
        errors.append(('assert', name))
    return bool(cond)


def css_visible(pg, sel):
    return pg.eval_on_selector(sel, 'e=>{const s=getComputedStyle(e);return s.display!=="none"&&s.visibility!=="hidden";}')


def attach(pg, tag=''):
    def on_pageerror(e):
        errors.append((f'pageerror{tag}', str(e)))
    pg.on('pageerror', on_pageerror)

    def on_console(m):
        if m.type != 'error':
            return
        t = m.text
        if ('ERR_FAILED' in t or 'Failed to load resource' in t
                or 'gstatic' in t or 'firebaseio' in t or 'net::' in t):
            return  # 被我们主动 abort 的 Firebase CDN，不算代码错误
        console_errs.append(f'{tag}{t}')
    pg.on('console', on_console)

    def on_dialog(d):
        dialogs.append(d.message)
        d.accept()  # confirm 需接受才能继续（alert 的 accept 等价 dismiss）
    pg.on('dialog', on_dialog)


def signup(pg, name, email, pwd):
    pg.evaluate("switchAuthTab('signup')")
    pg.wait_for_timeout(150)
    pg.fill('#signupName', name)
    pg.fill('#signupEmail', email)
    pg.fill('#signupPwd', pwd)
    pg.click('#signupBtn')
    pg.wait_for_timeout(900)


def signin(pg, email, pwd):
    pg.evaluate("switchAuthTab('signin')")
    pg.wait_for_timeout(150)
    pg.fill('#signinEmail', email)
    pg.fill('#signinPwd', pwd)
    pg.click('#signinBtn')
    pg.wait_for_timeout(900)


def logout(pg):
    pg.evaluate('doSignOut()')
    pg.wait_for_timeout(700)


def accounts(pg):
    return pg.evaluate("JSON.parse(localStorage.getItem('wb_local_accounts')||'[]')")


def acct(pg, email):
    for a in accounts(pg):
        if str(a.get('email', '')).lower() == email.lower():
            return a
    return None


def main():
    echarts_cache = ensure_echarts_cache()
    build_fake_site()
    proc_a, url_a = start_server(ROOT, free_port())       # 占位配置 → local
    proc_b, url_b = start_server(TMP_SITE, free_port())   # 假合法配置 → firebase
    print(f'  [INFO] 占位配置站点: {url_a}')
    print(f'  [INFO] 假合法配置站点: {url_b}')

    try:
        with sync_playwright() as p:
            b = launch_chromium(p)

            # ============ 站点 A：演示模式 + 预置演示管理员 ============
            ctx = b.new_context(viewport={'width': 1440, 'height': 900}, accept_downloads=True)
            ctx.route('**/*', make_router(echarts_cache))

            pg = ctx.new_page()
            attach(pg)
            pg.goto(url_a)
            pg.wait_for_timeout(1200)
            pg.evaluate('localStorage.clear(); sessionStorage.clear();')
            pg.reload()
            pg.wait_for_timeout(1500)

            print('=== A1) 首屏：占位配置 → 演示模式（无白屏）===')
            assert_true('authMode = local', pg.evaluate('state.authMode') == 'local',
                        pg.evaluate('state.authMode'))
            assert_true('登录卡片可见', css_visible(pg, '#loginView'))
            assert_true('演示模式登录横幅可见', css_visible(pg, '#loginLocalBanner'))
            assert_true('页面有实际内容（非白屏）', len(pg.text_content('#loginView').strip()) > 20)
            assert_true('Firebase 错误卡片默认隐藏', not css_visible(pg, '#firebaseErrCard'))

            print('=== A2) 预置演示管理员种子账号 ===')
            accs = accounts(pg)
            assert_true('首次加载自动写入 1 条账号', len(accs) == 1, len(accs))
            seed = acct(pg, SEED_EMAIL)
            assert_true('种子邮箱 = admin@workbuddy.local', seed is not None)
            assert_true('种子 role = admin', seed and seed.get('role') == 'admin')
            assert_true('种子 status = active', seed and seed.get('status') == 'active')
            assert_true('种子显示名 = 演示管理员', seed and seed.get('name') == '演示管理员')
            assert_true('种子带 16 位 salt', seed and len(seed.get('salt', '')) == 16)
            assert_true('口令为 SHA-256 hex（64 位、非 weak）',
                        seed and len(seed.get('passHash', '')) == 64
                        and not str(seed.get('passHash')).startswith('weak:'))
            raw = pg.evaluate("localStorage.getItem('wb_local_accounts')")
            assert_true('localStorage 无明文密码', SEED_PWD not in raw)
            assert_true('凭据卡可见', css_visible(pg, '#demoCredBox'))
            cred = pg.text_content('#demoCredBox') or ''
            assert_true('凭据卡展示邮箱', SEED_EMAIL in cred)
            assert_true('凭据卡展示密码', SEED_PWD in cred)
            assert_true('提示「仅存在本浏览器」', '本浏览器' in cred)
            assert_true('提示「任何人都能用这组凭据登录」', '任何访问本网址的人' in cred)
            assert_true('提示「接入 Firebase 后失效」', 'Firebase' in cred and '失效' in cred)

            print('=== A3) 一键填入并登录 → 管理员 ===')
            pg.click('#demoLoginBtn')
            pg.wait_for_timeout(1200)
            assert_true('进入看板', css_visible(pg, '.app'))
            assert_true('当前用户 = 种子账号', pg.evaluate('wbUser && wbUser.email') == SEED_EMAIL)
            assert_true('role = admin', pg.evaluate('wbUser.role') == 'admin')
            assert_true('侧栏管理后台入口可见', css_visible(pg, '#navAdmin'))
            assert_true('顶栏演示模式 chip 可见', css_visible(pg, '#modeChip'))
            assert_true('用户菜单显示当前模式', '演示模式' in (pg.text_content('#userMode') or ''))
            assert_true('总览 6 张指标卡', pg.eval_on_selector_all('#overviewStats .stat-card', 'e=>e.length') == 6)
            assert_true('用户菜单重置入口可见', css_visible(pg, '#userResetDemoLink'))

            print('=== A4) 刷新保持登录 ===')
            pg.reload()
            pg.wait_for_timeout(1500)
            assert_true('刷新后仍是看板', css_visible(pg, '.app'))
            assert_true('刷新后仍是种子管理员', pg.evaluate('wbUser && wbUser.email') == SEED_EMAIL)

            print('=== A5) 退出种子账号后注册第二个账号 → 普通用户 ===')
            logout(pg)
            signup(pg, 'Dave', 'dave@test.com', 'password1234')
            assert_true('注册后进入看板', css_visible(pg, '.app'))
            assert_true('Dave role = user', pg.evaluate('wbUser.role') == 'user')
            assert_true('Dave 无管理后台入口', not css_visible(pg, '#navAdmin'))
            assert_true('Dave 用户菜单无管理员链接', not css_visible(pg, '#userAdminLink'))
            pg.evaluate("switchPage('admin')")
            pg.wait_for_timeout(500)
            assert_true('Dave 强闯管理后台 → 无权限', '无权限' in (pg.text_content('#page-admin') or ''))

            print('=== A6) 报错用例 ===')
            logout(pg)
            signup(pg, 'Bad', 'not-an-email', 'password1234')
            assert_true('邮箱格式错误 → 中文报错', '邮箱格式不正确' in (pg.text_content('#signupErr') or ''),
                        pg.text_content('#signupErr'))
            signup(pg, 'Short', 'short@test.com', '123')
            assert_true('密码 <8 位 → 中文报错', '密码至少 8 位' in (pg.text_content('#signupErr') or ''))
            signup(pg, 'Dup', SEED_EMAIL, 'password1234')
            assert_true('重复邮箱 → 中文报错', '已注册' in (pg.text_content('#signupErr') or ''),
                        pg.text_content('#signupErr'))
            assert_true('报错时未进入看板', not css_visible(pg, '.app'))
            signin(pg, SEED_EMAIL, 'wrongpass123')
            assert_true('密码错误 → 中文报错', '密码错误' in (pg.text_content('#signinErr') or ''),
                        pg.text_content('#signinErr'))
            assert_true('密码错误未进入看板', not css_visible(pg, '.app'))

            print('=== A7) 管理员提权 / 禁用 / 启用 ===')
            signin(pg, SEED_EMAIL, SEED_PWD)
            assert_true('种子管理员登录成功', css_visible(pg, '.app') and pg.evaluate('wbUser.role') == 'admin')
            pg.evaluate("switchPage('admin')")
            pg.wait_for_timeout(600)
            assert_true('管理后台演示提示条可见', css_visible(pg, '#adminLocalNote'))
            assert_true('管理后台清空按钮区可见', css_visible(pg, '#adminLocalActions'))
            assert_true('管理后台 2 行', pg.eval_on_selector_all('#adminTbody tr', 'e=>e.length') == 2)
            dave_uid = acct(pg, 'dave@test.com')['uid']
            seed_uid = acct(pg, SEED_EMAIL)['uid']
            pg.evaluate(f"doAdminRole('{dave_uid}','admin')")
            pg.wait_for_timeout(500)
            assert_true('Dave 被提升为管理员', acct(pg, 'dave@test.com')['role'] == 'admin')

            print('=== A8) 防锁死：管理员不能降级/禁用自己 ===')
            pg.evaluate(f"doAdminRole('{seed_uid}','user')")
            pg.wait_for_timeout(400)
            assert_true('自我降级无效（仍 admin）', acct(pg, SEED_EMAIL)['role'] == 'admin')
            r1 = pg.evaluate(f"AuthAdapter.setRole('{seed_uid}','user').then(()=>'resolved',e=>e.code)")
            assert_true('适配层拒绝自我降级', r1 == 'local/failed-precondition', r1)
            r2 = pg.evaluate(f"AuthAdapter.setStatus('{seed_uid}','disabled').then(()=>'resolved',e=>e.code)")
            assert_true('适配层拒绝自我禁用', r2 == 'local/failed-precondition', r2)

            print('=== A9) 禁用 Dave → 登录被拒 + 跨标签页踢出 ===')
            pg.evaluate(f"doAdminStatus('{dave_uid}','disabled')")
            pg.wait_for_timeout(500)
            assert_true('Dave 状态 = disabled', acct(pg, 'dave@test.com')['status'] == 'disabled')
            logout(pg)
            signin(pg, 'dave@test.com', 'password1234')
            assert_true('被禁账号登录被拒', '禁用' in (pg.text_content('#signinErr') or ''),
                        pg.text_content('#signinErr'))
            assert_true('被禁账号未进入看板', not css_visible(pg, '.app'))
            # 恢复启用 → Dave 登录 → 另一标签页禁用 → 本页被踢
            signin(pg, SEED_EMAIL, SEED_PWD)
            pg.evaluate(f"doAdminStatus('{dave_uid}','active')")
            pg.wait_for_timeout(400)
            logout(pg)
            signin(pg, 'dave@test.com', 'password1234')
            assert_true('Dave 重新登录成功', css_visible(pg, '.app'))
            tab2 = ctx.new_page()
            attach(tab2, '[tab2] ')
            tab2.goto(url_a)
            tab2.wait_for_timeout(1500)
            if tab2.evaluate('!!wbUser'):
                tab2.evaluate('doSignOut()')
                tab2.wait_for_timeout(700)
            signin(tab2, SEED_EMAIL, SEED_PWD)
            assert_true('tab2 种子管理员登录成功', css_visible(tab2, '.app'))
            tab2.evaluate(f"doAdminStatus('{dave_uid}','disabled')")
            tab2.wait_for_timeout(900)
            assert_true('tab1 Dave 被踢出（回到登录页）', css_visible(pg, '#loginView'))
            assert_true('tab1 提示已被禁用', '禁用' in (pg.text_content('#signinErr') or ''),
                        pg.text_content('#signinErr'))
            tab2.close()

            print('=== A10) 业务回归（10 页 + 筛选 + CSV + 保存报表）===')
            signin(pg, SEED_EMAIL, SEED_PWD)
            assert_true('种子管理员回到看板', css_visible(pg, '.app'))
            pages = ['overview', 'org', 'users', 'tasks', 'category',
                     'position', 'prompt', 'dialogue', 'upload', 'report']
            ok_pages = True
            for name in pages:
                pg.evaluate(f"switchPage('{name}')")
                pg.wait_for_timeout(400)
                if not pg.eval_on_selector(f'#page-{name}', 'e=>getComputedStyle(e).display!=="none"'):
                    ok_pages = False
                    print('    页面不可见:', name)
            assert_true('10 个业务页均可正常渲染', ok_pages)
            base = pg.evaluate('getFilteredTasks().length')
            pg.evaluate("applyRange('month')")
            pg.wait_for_timeout(500)
            n_month = pg.evaluate('getFilteredTasks().length')
            assert_true('时间筛选生效（本月 < 近90天）', n_month < base and n_month > 0, f'{n_month} < {base}')
            pg.evaluate("applyRange('today')")
            pg.wait_for_timeout(400)
            n_today = pg.evaluate('getFilteredTasks().length')
            assert_true('时间筛选生效（今日 < 本月）', n_today < n_month, f'{n_today} < {n_month}')
            pg.evaluate("applyRange('90d')")
            pg.wait_for_timeout(400)
            assert_true('恢复近90天', pg.evaluate('getFilteredTasks().length') == base)
            pg.evaluate("switchPage('users')")
            pg.wait_for_timeout(400)
            try:
                with pg.expect_download(timeout=5000) as dl:
                    pg.evaluate('exportUsers()')
                assert_true('CSV 导出可用', dl.value.suggested_filename.endswith('.csv'),
                            dl.value.suggested_filename)
            except Exception as e:
                assert_true('CSV 导出可用', False, str(e)[:120])
            pg.evaluate("switchPage('report')")
            pg.wait_for_timeout(400)
            pg.evaluate("generateReport()")
            pg.wait_for_timeout(400)
            assert_true('自定义报表生成有结果表',
                        pg.eval_on_selector_all('#reportTable tbody tr', 'e=>e.length') > 0)
            pg.evaluate("saveReport()")
            pg.wait_for_timeout(400)
            assert_true('保存自定义报表成功',
                        pg.evaluate("JSON.parse(localStorage.getItem('wb_saved_reports')||'[]').length") >= 1)

            print('=== A11) 演示模式下真实数据源置灰并拦截 ===')
            assert_true('真实数据源选项置灰', 'disabled' in (pg.get_attribute('#dsOptReal', 'class') or ''))
            assert_true('置灰有 tooltip 说明', len(pg.get_attribute('#dsOptReal', 'title') or '') > 10)
            dialogs.clear()
            pg.click('#dsOptReal')
            pg.wait_for_timeout(500)
            assert_true('点击真实数据源被拦截并提示', any('演示模式' in d for d in dialogs))
            assert_true('数据源仍为 mock', pg.evaluate('DATA.source') == 'mock')

            print('=== A12) 重置：清空本地演示账号 ===')
            pg.evaluate("switchPage('admin')")
            pg.wait_for_timeout(500)
            dialogs.clear()
            pg.click('#adminResetBtn')
            pg.wait_for_timeout(1200)
            assert_true('清空前二次确认弹窗', any('清空' in d for d in dialogs), dialogs[:1])
            assert_true('账号表已清空', len(accounts(pg)) == 0, len(accounts(pg)))
            assert_true('会话已清除', pg.evaluate("localStorage.getItem('wb_local_session')") is None)
            assert_true('跳回登录页', css_visible(pg, '#loginView'))
            assert_true('登录页给出清空提示', '已清空' in (pg.text_content('#signinErr') or ''),
                        pg.text_content('#signinErr'))
            # 刷新 → 种子账号再次生成
            pg.reload()
            pg.wait_for_timeout(1500)
            assert_true('刷新后种子账号重新生成', acct(pg, SEED_EMAIL) is not None)
            assert_true('重新生成的种子仍是管理员', acct(pg, SEED_EMAIL)['role'] == 'admin')
            # 再清空一次 → 不刷新直接注册 → 首个账号为管理员
            signin(pg, SEED_EMAIL, SEED_PWD)
            pg.evaluate("switchPage('admin')")
            pg.wait_for_timeout(500)
            pg.click('#adminResetBtn')
            pg.wait_for_timeout(1200)
            assert_true('再次清空成功', len(accounts(pg)) == 0)
            signup(pg, 'Erin', 'erin@test.com', 'password1234')
            assert_true('清空后首个注册账号 = admin', pg.evaluate('wbUser.role') == 'admin')
            assert_true('Erin 邮箱正确', pg.evaluate('wbUser && wbUser.email') == 'erin@test.com')
            ctx.close()

            # ============ 站点 B：假合法配置 → 云端模式 ============
            print('=== B1) 假合法配置 → firebase 模式，无 SDK → 错误卡片（非白屏）===')
            assert_true('假配置站点服务仍存活', proc_b.poll() is None, proc_b.poll())
            ctx2 = b.new_context(viewport={'width': 1440, 'height': 900})
            ctx2.route('**/*', make_router(echarts_cache))
            pg2 = ctx2.new_page()
            attach(pg2, '[B1] ')
            pg2.goto(url_b)
            pg2.wait_for_timeout(1500)
            assert_true('authMode = firebase', pg2.evaluate('state.authMode') == 'firebase',
                        pg2.evaluate('state.authMode'))
            assert_true('未白屏（登录卡片可见）', css_visible(pg2, '#loginView'))
            assert_true('友好错误卡片可见', css_visible(pg2, '#firebaseErrCard'))
            assert_true('错误卡片为可读中文', 'Firebase' in (pg2.text_content('#firebaseErrBody') or ''))
            assert_true('云端模式不创建种子账号',
                        pg2.evaluate("localStorage.getItem('wb_local_accounts')") is None)
            assert_true('云端模式不显示演示凭据卡', not css_visible(pg2, '#demoCredBox'))
            assert_true('云端模式不显示演示模式横幅', not css_visible(pg2, '#loginLocalBanner'))
            print('=== B1b) 一键降级 → 演示模式（种子随之生成）===')
            pg2.click('#useLocalDemoBtn')
            pg2.wait_for_timeout(1200)
            assert_true('降级后 authMode = local', pg2.evaluate('state.authMode') == 'local')
            assert_true('降级后错误卡片隐藏', not css_visible(pg2, '#firebaseErrCard'))
            assert_true('降级后生成种子账号', acct(pg2, SEED_EMAIL) is not None)
            pg2.click('#demoLoginBtn')
            pg2.wait_for_timeout(1200)
            assert_true('降级后可用种子账号登录', css_visible(pg2, '.app'))
            assert_true('降级后种子为管理员', pg2.evaluate('wbUser.role') == 'admin')
            ctx2.close()

            print('=== B2) SDK 存在但初始化抛错 → 错误卡片（非白屏）===')
            ctx3 = b.new_context(viewport={'width': 1440, 'height': 900})
            ctx3.route('**/*', make_router(echarts_cache))
            ctx3.add_init_script(
                "Object.defineProperty(window,'firebase',{configurable:true,value:{"
                "  initializeApp:function(){throw new Error('stub init boom');}"
                "}});"
            )
            pg3 = ctx3.new_page()
            attach(pg3, '[B2] ')
            pg3.goto(url_b)
            pg3.wait_for_timeout(1500)
            assert_true('authMode = firebase', pg3.evaluate('state.authMode') == 'firebase')
            assert_true('未白屏（登录卡片可见）', css_visible(pg3, '#loginView'))
            assert_true('友好错误卡片可见', css_visible(pg3, '#firebaseErrCard'))
            body = pg3.text_content('#firebaseErrBody') or ''
            assert_true('错误卡片包含初始化失败原因', 'stub init boom' in body)
            assert_true('错误卡片给出降级指引', '演示模式' in body)
            assert_true('云端模式不创建种子账号',
                        pg3.evaluate("localStorage.getItem('wb_local_accounts')") is None)
            ctx3.close()

            b.close()
    finally:
        for proc in (proc_a, proc_b):
            try:
                proc.kill()
            except Exception:
                pass
        shutil.rmtree(TMP_SITE, ignore_errors=True)

    print()
    print('PAGE ERRORS  :', errors if errors else 'none')
    print('CONSOLE ERRORS:', console_errs if console_errs else 'none')
    print('OVERALL:', 'PASS' if (not errors and not console_errs) else 'FAIL')
    return 0 if (not errors and not console_errs) else 1


if __name__ == '__main__':
    raise SystemExit(main())
