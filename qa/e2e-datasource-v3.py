#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QA v3 独立 E2E（software-qa-engineer-3，严过关）
对「WorkBuddy Open API 双数据源接入」的独立验证 —— 不复用工程师的测试脚本，
使用 qa/firebase-mock-v3.js（字段名/状态值刻意与工程师 mock 不同）。

覆盖：
  S1  未登录点真实数据源 → 拦截提示，不切换
  S2  注册登录（首用户 admin）
  S3  未授权切真实源 → 引导卡片 + 回退 Mock + 偏好回写 mock
  S4  点「去授权」→ 拦截导航，逐字段校验 authorize URL（response_type/client_id/
      redirect_uri 字节级一致且编码/scope/state），state 与 sessionStorage 一致
  S5  真实源渲染：8 条任务分类映射、状态映射（混合大小写）、时间筛选（week=7 /
      自定义宽区间=8）、任务明细表、API 提示条、CSV 导出
  S6  切换稳定性：Mock→Real→Mock ×3 轮 + 期间施加筛选，TASKS 与基线 JSON 逐一相等；
      刷新页面后 Mock 数据与基线一致（固定种子）
  S7  真实源登出 → 自动回退 Mock；重新登录 → 恢复 real 偏好自动拉取
  S8  断开授权 wbDisconnect → 回退 Mock + 偏好 mock
  S9  回调页（路由映射到登记的 https 地址）：
      - happy path：state 匹配 → callable 收到正确 code/redirectUri → 成功文案 →
        sessionStorage 清除 → localStorage wb_data_source=real → 跳回 ../../
      - state 不匹配 / 无 code / error 参数 / 未登录 → 显示错误且不调 callable
"""
import os, pathlib, sys
from urllib.parse import urlparse, parse_qs, unquote

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
MOCK = (pathlib.Path(__file__).resolve().parent / 'firebase-mock-v3.js').read_text(encoding='utf-8')
CALLBACK_HTML = (ROOT / 'oauth/callback/index.html').read_text(encoding='utf-8')
INDEX_HTML = (ROOT / 'index.html').read_text(encoding='utf-8')
REGISTERED = 'https://pyt083.github.io/workbuddy-analytics/oauth/callback'

results = []
def check(name, cond, evidence=''):
    results.append((bool(cond), name))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f'  | {evidence}' if evidence else ''))
    return bool(cond)

def block_cdn(route, request):
    url = request.url
    if 'gstatic.com' in url or 'firebaseio.com' in url:
        route.abort()
    else:
        route.continue_()

with sync_playwright() as p:
    try:
        browser = p.chromium.launch()
    except Exception:
        import glob
        exe = sorted(glob.glob(os.path.expanduser(
            '~/Library/Caches/ms-playwright/chromium-*/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing')), reverse=True)[0]
        browser = p.chromium.launch(executable_path=exe)

    # ============ 主页面上下文 ============
    ctx = browser.new_context(viewport={'width': 1440, 'height': 900})
    ctx.route('**/*', block_cdn)
    ctx.add_init_script(MOCK)
    pg = ctx.new_page()
    page_errors = []
    pg.on('pageerror', lambda e: page_errors.append(str(e)))

    print('=== S1 未登录点「我的 WorkBuddy 数据」===')
    pg.goto((ROOT / 'index.html').as_uri())
    pg.wait_for_timeout(2000)
    check('S1.1 登录视图可见', pg.eval_on_selector('#loginView', 'e=>getComputedStyle(e).display!=="none"'))
    # 登录视图下切换器不可见，直接触发其点击处理函数（逻辑层验证：未登录拦截）
    pg.evaluate("document.getElementById('dsOptReal').click()"); pg.wait_for_timeout(400)
    check('S1.2 未登录切换被拦截，仍为 Mock', pg.evaluate('DATA.source') == 'mock',
          pg.evaluate('DATA.source'))
    check('S1.3 未登录不写 real 偏好', pg.evaluate("localStorage.getItem('wb_data_source')||'mock'") != 'real')

    print('=== S2 注册登录（首用户 admin）===')
    pg.evaluate("switchAuthTab('signup')"); pg.wait_for_timeout(150)
    pg.fill('#signupName', 'QA3User'); pg.fill('#signupEmail', 'qa3user@v3.test'); pg.fill('#signupPwd', 'password1234')
    pg.click('#signupBtn'); pg.wait_for_timeout(2200)
    check('S2.1 进入看板', pg.eval_on_selector('.app', 'e=>getComputedStyle(e).display!=="none"'),
          'signupErr=' + repr((pg.text_content('#signupErr') or '')[:60]))
    check('S2.2 首注册用户为 admin', (pg.evaluate('wbUser&&wbUser.role') or '') == 'admin', str(pg.evaluate('wbUser&&wbUser.role')))

    # 记录 Mock 基线（S6 用）
    mock_baseline = pg.evaluate('JSON.stringify(TASKS)')
    mock_count = pg.evaluate('TASKS.length')
    check('S2.3 Mock 基线数据量 > 100', mock_count > 100, str(mock_count))

    print('=== S3 未授权切真实源 → 引导卡片 ===')
    pg.evaluate("window.__V3WB__.mode='noauth'")
    pg.click('#dsOptReal'); pg.wait_for_timeout(1200)
    check('S3.1 拉取失败回退 Mock', pg.evaluate('DATA.source') == 'mock')
    check('S3.2 引导卡片出现', pg.eval_on_selector('#apiGuideCard', 'e=>getComputedStyle(e).display!=="none"'))
    check('S3.3 「去授权」按钮可见', pg.eval_on_selector('#wbAuthBtn', 'e=>getComputedStyle(e).display!=="none"'))
    check('S3.4 错误提示非空', len((pg.text_content('#wbGuideErr') or '').strip()) > 0)
    check('S3.5 偏好回写 mock', pg.evaluate("localStorage.getItem('wb_data_source')") == 'mock')

    print('=== S5 真实源渲染（mode=ok）===')
    pg.evaluate("window.__V3WB__.mode='ok'")
    pg.click('#dsOptReal'); pg.wait_for_timeout(1500)
    check('S5.1 DATA.source=api', pg.evaluate('DATA.source') == 'api')
    check('S5.2 任务数=8（mock 提供字段名 title/id 兼容）', pg.evaluate('TASKS.length') == 8,
          str(pg.evaluate('TASKS.length')))
    cats = pg.evaluate('TASKS.map(t=>t.category)')
    check('S5.3 分类映射：PPT 制作', cats[0] == 'PPT制作', str(cats[0]))
    check('S5.4 分类映射：翻译', cats[1] == '翻译', str(cats[1]))
    check('S5.5 分类映射：图片设计', cats[2] == '图片设计', str(cats[2]))
    check('S5.6 分类映射：代码开发', cats[3] == '代码开发', str(cats[3]))
    check('S5.7 分类映射：数据分析', cats[4] == '数据分析', str(cats[4]))
    check('S5.8 分类映射：文档写作', cats[5] == '文档写作', str(cats[5]))
    check('S5.9 分类映射：视频生成', cats[6] == '视频生成', str(cats[6]))
    sts = pg.evaluate('TASKS.map(t=>t.status)')
    check('S5.10 状态映射（Completed/running/FAILED/CANCELLED/completed/succeeded/undefined/done）',
          sts == ['已完成', '进行中', '已取消', '已取消', '已完成', '已完成', '进行中', '已完成'], str(sts))
    check('S5.11 rounds/outCount/upCount 置 0', pg.evaluate('TASKS.every(t=>t.rounds===0&&t.outCount===0&&t.upCount===0)'))
    check('S5.12 用户=授权账号', pg.evaluate("USERS[0].dept") == '授权账号')
    check('S5.13 昵称取自 profile', pg.evaluate("USERS[0].name") == '严过关测试号', pg.evaluate("USERS[0].name||''"))
    # 时间筛选：1 条任务在 200 天前
    pg.evaluate("applyRange('week')"); pg.wait_for_timeout(300)
    check('S5.14 本周筛选 = 7 条（200 天前的被排除）', pg.evaluate('getFilteredTasks().length') == 7,
          str(pg.evaluate('getFilteredTasks().length')))
    pg.evaluate("""() => {
      document.getElementById('dateFrom').value = '2020-01-01';
      document.getElementById('dateTo').value = '2099-12-31';
    }""")
    pg.evaluate("applyRange('custom')"); pg.wait_for_timeout(300)
    check('S5.15 自定义宽区间 = 8 条', pg.evaluate('getFilteredTasks().length') == 8,
          str(pg.evaluate('getFilteredTasks().length')))
    # 任务明细页
    pg.evaluate("switchPage('tasks')"); pg.wait_for_timeout(400)
    task_text = pg.text_content('#taskTbody') or ''
    check('S5.16 任务表含真实任务 ID（id 字段回退）', 'T9001' in task_text)
    check('S5.17 任务表含真实标题（title 字段回退）', '季度产品发布会 PPT' in task_text)
    # API 提示条
    for pid, nid in [('prompt', 'apiNotePrompt'), ('dialogue', 'apiNoteDialogue'), ('upload', 'apiNoteUpload'), ('org', 'apiNoteOrg')]:
        pg.evaluate(f"switchPage('{pid}')"); pg.wait_for_timeout(300)
        check(f'S5.18 {pid} 页 API 提示条可见', pg.eval_on_selector(f'#{nid}', 'e=>getComputedStyle(e).display!=="none"'))
    # CSV 导出（真实数据下）
    pg.evaluate("switchPage('tasks')"); pg.wait_for_timeout(400)
    try:
        with pg.expect_download(timeout=4000) as dl:
            pg.evaluate('exportTasks()')
        fn = dl.value.suggested_filename
        check('S5.19 真实数据源导出任务 CSV', True, fn)
    except Exception as e:
        check('S5.19 真实数据源导出任务 CSV', False, str(e)[:80])
    check('S5.20 偏好 = real', pg.evaluate("localStorage.getItem('wb_data_source')") == 'real')
    real_calls_1 = pg.evaluate('__V3CALLS__.filter(c=>c.name==="wbGetMyTasks").length')
    check('S5.21 wbGetMyTasks 已被调用', real_calls_1 >= 1, str(real_calls_1))

    print('=== S6 切换稳定性（3 轮 Mock↔Real + 筛选干扰 + 刷新）===')
    for i in range(3):
        pg.click('#dsOptMock'); pg.wait_for_timeout(400)
        ok_src = pg.evaluate('DATA.source') == 'mock'
        ok_json = pg.evaluate('JSON.stringify(TASKS)') == mock_baseline
        check(f'S6.{i+1}a 第{i+1}轮回 Mock：source=mock 且 TASKS 与基线 JSON 相等', ok_src and ok_json)
        # 干扰：Mock 模式下应用筛选、翻页
        pg.evaluate("applyRange('week')"); pg.wait_for_timeout(200)
        pg.evaluate("switchPage('users')"); pg.wait_for_timeout(250)
        pg.click('#dsOptReal'); pg.wait_for_timeout(1200)
        check(f'S6.{i+1}b 第{i+1}轮切真实源成功', pg.evaluate('DATA.source') == 'api' and pg.evaluate('TASKS.length') == 8)
    pg.click('#dsOptMock'); pg.wait_for_timeout(400)
    check('S6.4a 最终回 Mock source=mock', pg.evaluate('DATA.source') == 'mock')
    check('S6.4b 最终回 Mock TASKS 与基线一致', pg.evaluate('JSON.stringify(TASKS)') == mock_baseline)
    # 刷新页面后 Mock 一致性（固定种子）——刷新后 mock 内存清空，需重新注册
    pg.evaluate("localStorage.setItem('wb_data_source','mock')")
    pg.reload(); pg.wait_for_timeout(2000)
    pg.evaluate("switchAuthTab('signup')"); pg.wait_for_timeout(150)
    pg.fill('#signupName', 'QA3User'); pg.fill('#signupEmail', 'qa3user@v3.test'); pg.fill('#signupPwd', 'password1234')
    pg.click('#signupBtn'); pg.wait_for_timeout(2200)
    check('S6.5 刷新后重新登录成功', pg.eval_on_selector('.app', 'e=>getComputedStyle(e).display!=="none"'),
          'signupErr=' + repr((pg.text_content('#signupErr') or '')[:40]))
    check('S6.6 刷新后 Mock 数据与基线一致（固定种子）', pg.evaluate('JSON.stringify(TASKS)') == mock_baseline)

    print('=== S7 登出回退 + 重登恢复偏好 ===')
    pg.click('#dsOptReal'); pg.wait_for_timeout(1200)
    check('S7.1 切回真实源', pg.evaluate('DATA.source') == 'api')
    pg.evaluate('doSignOut()'); pg.wait_for_timeout(900)
    check('S7.2 登出后回退 Mock', pg.evaluate('DATA.source') == 'mock')
    check('S7.3 登出后回登录页', pg.eval_on_selector('#loginView', 'e=>getComputedStyle(e).display!=="none"'))
    # 重新登录：偏好仍是 real → 自动切真实源
    pg.evaluate("switchAuthTab('signin')"); pg.wait_for_timeout(150)
    pg.fill('#signinEmail', 'qa3user@v3.test'); pg.fill('#signinPwd', 'password1234')
    pg.click('#signinBtn'); pg.wait_for_timeout(2500)
    check('S7.4 重登后自动恢复真实数据源（偏好 real）', pg.evaluate('DATA.source') == 'api',
          pg.evaluate('DATA.source'))
    # 登出后偏好被服务端拒绝（token 失效）→ 重登回退 mock 并引导
    pg.evaluate('doSignOut()'); pg.wait_for_timeout(800)
    pg.evaluate("window.__V3WB__.mode='noauth'")
    pg.evaluate("switchAuthTab('signin')"); pg.wait_for_timeout(150)
    pg.fill('#signinEmail', 'qa3user@v3.test'); pg.fill('#signinPwd', 'password1234')
    pg.click('#signinBtn'); pg.wait_for_timeout(2500)
    check('S7.5 token 失效重登 → 回退 Mock', pg.evaluate('DATA.source') == 'mock', pg.evaluate('DATA.source'))
    check('S7.6 引导卡片重新出现', pg.eval_on_selector('#apiGuideCard', 'e=>getComputedStyle(e).display!=="none"'))

    print('=== S8 断开授权 ===')
    pg.evaluate("window.__V3WB__.mode='ok'")
    pg.click('#dsOptReal'); pg.wait_for_timeout(1200)
    pg.on('dialog', lambda d: d.accept())
    pg.evaluate("switchPage('overview')"); pg.wait_for_timeout(300)
    pg.click('#wbDisconnectBtn'); pg.wait_for_timeout(1200)
    check('S8.1 wbDisconnect 已被调用', pg.evaluate('__V3CALLS__.some(c=>c.name==="wbDisconnect")'))
    check('S8.2 断开后回退 Mock', pg.evaluate('DATA.source') == 'mock')
    check('S8.3 偏好回写 mock', pg.evaluate("localStorage.getItem('wb_data_source')") == 'mock')

    check('S9.0 主页面无 JS 报错', not page_errors, '; '.join(page_errors[:3]))
    ctx.close()

    # ============ OAuth 全链路往返（独立上下文，路由映射到登记的 https 源）============
    print('=== S4 OAuth 全链路：主页 → authorize(mock 302) → 回调页 → callable → 跳回主页 ===')
    ctx2 = browser.new_context(viewport={'width': 1440, 'height': 900})
    captured = {}
    MAIN_URL = 'https://pyt083.github.io/workbuddy-analytics/'

    def oauth_roundtrip_route(route, request):
        url = request.url
        if 'gstatic.com' in url or 'firebaseio.com' in url:
            route.abort()
        elif 'www.workbuddy.cn' in url:
            # mock 授权端点：记录 URL；用 JS location.replace 回跳（route.fulfill 的 302
            # 重定向目标不会重新进入 Playwright 路由拦截，故改用 JS 导航模拟授权回跳）
            captured['url'] = url
            q = parse_qs(urlparse(url).query)
            st = (q.get('state') or [''])[0]
            body = "<script>location.replace('" + REGISTERED + "?code=RT_CODE_123&state=" + st + "')</script>"
            route.fulfill(status=200, content_type='text/html', body=body)
        elif url.startswith('https://pyt083.github.io/workbuddy-analytics/oauth/callback'):
            route.fulfill(status=200, content_type='text/html', body=CALLBACK_HTML)
        elif url.rstrip('/').endswith('/workbuddy-analytics') or url.endswith('/workbuddy-analytics/'):
            route.fulfill(status=200, content_type='text/html', body=INDEX_HTML)
        elif url.rstrip('/').endswith('/workbuddy-analytics/index.html'):
            route.fulfill(status=200, content_type='text/html', body=INDEX_HTML)
        elif url in ('https://pyt083.github.io/', 'https://pyt083.github.io/'):
            # 回调页 '../../' 的实际解析目标（浏览器证据）—— 记录并返回标记页
            captured['final_nav'] = url
            route.fulfill(status=200, content_type='text/html', body='<h1 id="pagesroot">PAGES-ROOT</h1>')
        elif url.startswith('https://pyt083.github.io/'):
            route.abort()
        else:
            route.continue_()
    ctx2.route('**/*', oauth_roundtrip_route)
    ctx2.add_init_script(MOCK)
    pg2 = ctx2.new_page()
    pg2.goto(MAIN_URL)
    pg2.wait_for_timeout(2500)
    pg2.evaluate("switchAuthTab('signup')"); pg2.wait_for_timeout(150)
    pg2.fill('#signupName', 'BobV3'); pg2.fill('#signupEmail', 'bob@v3.test'); pg2.fill('#signupPwd', 'password1234')
    pg2.click('#signupBtn'); pg2.wait_for_timeout(2200)
    check('S4.1 主页（路由映射到 Pages 源）登录完成', pg2.eval_on_selector('.app', 'e=>getComputedStyle(e).display!=="none"'))
    saved_state = pg2.evaluate("sessionStorage.getItem('wb_oauth_state')")
    check('S4.2 点击前 state 未生成', saved_state in (None, ''))
    pg2.evaluate("window.__V3WB__.mode='noauth'")
    pg2.evaluate("switchPage('overview')"); pg2.wait_for_timeout(300)
    pg2.click('#dsOptReal'); pg2.wait_for_timeout(1200)
    check('S4.2b 引导卡片出现（未授权）', pg2.eval_on_selector('#apiGuideCard', 'e=>getComputedStyle(e).display!=="none"'))
    pg2.click('#wbAuthBtn')
    # 授权页 302 → 回调页 → callable → 1200ms 后跳回 ../../（= /workbuddy-analytics/）
    pg2.wait_for_url('**/workbuddy-analytics/**', timeout=15000)
    pg2.wait_for_timeout(2500)
    au = captured.get('url', '')
    check('S4.3 发生了对 workbuddy.cn 的跳转', au.startswith('https://www.workbuddy.cn/openapi/v2/authorize'), au[:60])
    q = parse_qs(urlparse(au).query)
    check('S4.4 response_type=code', q.get('response_type') == ['code'])
    check('S4.5 client_id=cb_YipjG5TEevNZFIblffrL', q.get('client_id') == ['cb_YipjG5TEevNZFIblffrL'])
    check('S4.6 redirect_uri 解码后与登记地址字节级一致', q.get('redirect_uri') == [REGISTERED], str(q.get('redirect_uri')))
    check('S4.7 redirect_uri 已 URL 编码（: / 均编码）', 'redirect_uri=https%3A%2F%2F' in au)
    check('S4.8 scope 正确', q.get('scope') == ['user.profile.readable user.task.readable'], str(q.get('scope')))
    st = (q.get('state') or [''])[0]
    check('S4.9 state 非空（≥16 字符）', len(st) >= 16, st)
    # 回跳落点（P1-2 已修复：回调页改用绝对路径 WB_HOME='/workbuddy-analytics/'）。
    # 断言当前页面落回看板 /workbuddy-analytics/，而非站点根 https://pyt083.github.io/
    final_url = pg2.url
    check('S4.10 授权成功后回跳到看板（/workbuddy-analytics/，不落站点根）',
          final_url.rstrip('/').endswith('/workbuddy-analytics') and final_url != 'https://pyt083.github.io/',
          f'实际回跳落点: {final_url}')
    pg2.wait_for_timeout(500)
    check('S4.11 回调成功写入偏好 wb_data_source=real',
          pg2.evaluate("localStorage.getItem('wb_data_source')") == 'real',
          pg2.evaluate("localStorage.getItem('wb_data_source')"))
    # 用户手动回到看板后重登，按偏好自动切真实源（mock 内存按页重置，重新注册）
    pg2.goto(MAIN_URL); pg2.wait_for_timeout(2000)
    pg2.evaluate("switchAuthTab('signup')"); pg2.wait_for_timeout(150)
    pg2.fill('#signupName', 'BobV3'); pg2.fill('#signupEmail', 'bob@v3.test'); pg2.fill('#signupPwd', 'password1234')
    pg2.click('#signupBtn'); pg2.wait_for_timeout(2800)
    check('S4.12 重登后按偏好自动切真实数据源', pg2.evaluate('DATA.source') == 'api',
          str(pg2.evaluate('DATA.source')))
    check('S4.13 任务数=8（真实源渲染）', pg2.evaluate('TASKS.length') == 8, str(pg2.evaluate('TASKS.length')))
    ctx2.close()

    # ============ 回调页（路由映射到登记地址）============
    print('=== S9 回调页 oauth/callback/index.html ===')
    ctx3 = browser.new_context(viewport={'width': 1440, 'height': 900})
    cb_errors = []
    nav_attempts = []

    def cb_route(route, request):
        url = request.url
        if 'gstatic.com' in url or 'firebaseio.com' in url:
            route.abort()
        elif url.startswith('https://pyt083.github.io/workbuddy-analytics/oauth/callback'):
            route.fulfill(status=200, content_type='text/html', body=CALLBACK_HTML)
        elif url.startswith('https://pyt083.github.io/'):
            nav_attempts.append(url)
            route.abort()
        elif 'www.workbuddy.cn' in url:
            route.abort()  # retryBtn 重新授权
        else:
            route.continue_()
    ctx3.route('**/*', cb_route)
    ctx3.add_init_script(MOCK)
    cb = ctx3.new_page()
    cb.on('pageerror', lambda e: cb_errors.append(str(e)))

    BASE_CB = 'https://pyt083.github.io/workbuddy-analytics/oauth/callback'

    # --- happy path ---
    cb.goto(BASE_CB + '?code=CODE_V3_123&state=v3stateTOKEN123&presetstate=1')
    cb.wait_for_timeout(900)
    main_txt = cb.text_content('#main') or ''
    check('S9.1 happy path：显示授权成功', '授权成功' in main_txt, main_txt[:60])
    calls1 = cb.evaluate('__V3CALLS__.filter(c=>c.name==="wbOauthCallback")')
    check('S9.2 调用了 wbOauthCallback 恰好 1 次', len(calls1) == 1, str(len(calls1)))
    if calls1:
        check('S9.3 code 透传正确', calls1[0]['data'] and calls1[0]['data'].get('code') == 'CODE_V3_123')
        check('S9.4 redirectUri 与登记地址字节级一致',
              calls1[0]['data'].get('redirectUri') == REGISTERED, str(calls1[0]['data'].get('redirectUri')))
    check('S9.5 成功后清除 sessionStorage state', cb.evaluate("sessionStorage.getItem('wb_oauth_state')") in (None, ''))
    check('S9.6 成功后写 localStorage wb_data_source=real', cb.evaluate("localStorage.getItem('wb_data_source')") == 'real')
    cb.wait_for_timeout(1600)  # 1200ms 后回跳
    # 实测：'../../' 相对基址 /workbuddy-analytics/oauth/callback 解析为站点根，
    # 而非看板 /workbuddy-analytics/ —— 记录为 P1 产品缺陷证据
    check('S9.7 成功后回跳目标为看板（期望 /workbuddy-analytics/）',
          any(u.rstrip('/').endswith('/workbuddy-analytics') for u in nav_attempts),
          '实际回跳目标: ' + (nav_attempts[0] if nav_attempts else '(未捕获)'))

    # --- state 不匹配 ---
    calls_before = cb.evaluate('__V3CALLS__.length')
    cb.goto(BASE_CB + '?code=X1&state=WRONGSTATE')
    cb.wait_for_timeout(900)
    t2 = cb.text_content('#main') or ''
    check('S9.8 state 不匹配 → 显示校验失败', 'state 校验失败' in t2)
    check('S9.9 state 不匹配 → 未调 callable',
          cb.evaluate('__V3CALLS__.length') == calls_before)
    check('S9.10 state 不匹配 → 显示重试按钮', cb.eval_on_selector('#actions', 'e=>getComputedStyle(e).display!=="none"'))

    # --- 无 code ---
    cb.goto(BASE_CB + '?state=v3stateTOKEN123&presetstate=1')
    cb.wait_for_timeout(900)
    t3 = cb.text_content('#main') or ''
    check('S9.11 无 code → 提示缺少授权码', '缺少授权码' in t3)

    # --- provider error ---
    calls_before = cb.evaluate('__V3CALLS__.length')
    cb.goto(BASE_CB + '?error=access_denied&error_description=user+denied')
    cb.wait_for_timeout(900)
    t4 = cb.text_content('#main') or ''
    check('S9.12 error 参数 → 显示授权被拒绝', 'access_denied' in t4 and '拒绝' in t4)
    check('S9.13 error 参数 → 未调 callable', cb.evaluate('__V3CALLS__.length') == calls_before)

    # --- 未登录（nologin=1 禁用 mock 自动登录）---
    cb.goto(BASE_CB + '?code=X2&state=v3stateTOKEN123&presetstate=1&nologin=1')
    cb.wait_for_timeout(900)
    t5 = cb.text_content('#main') or ''
    check('S9.14 未登录 → 提示先登录看板账号', '请先登录看板账号' in t5, t5[:60])
    check('S9.15 未登录 → 未调 callable', cb.evaluate('__V3CALLS__.length') == calls_before)

    # --- retryBtn 重新授权按钮生成新 state 并跳授权页 ---
    wb_captured = {}
    def cb_route2(route, request):
        url = request.url
        if 'gstatic.com' in url or 'firebaseio.com' in url:
            route.abort()
        elif url.startswith('https://pyt083.github.io/workbuddy-analytics/oauth/callback'):
            route.fulfill(status=200, content_type='text/html', body=CALLBACK_HTML)
        elif url.startswith('https://pyt083.github.io/'):
            route.abort()
        elif 'workbuddy.cn' in url:
            wb_captured['url'] = url
            route.abort()
        else:
            route.continue_()
    ctx3.unroute('**/*')
    ctx3.route('**/*', cb_route2)
    cb.goto(BASE_CB + '?code=X1&state=WRONGSTATE')
    cb.wait_for_timeout(600)
    cb.click('#retryBtn'); cb.wait_for_timeout(900)
    au2 = wb_captured.get('url', '')
    q2 = parse_qs(urlparse(au2).query)
    check('S9.16 重新授权按钮跳授权端点且参数完整',
          au2.startswith('https://www.workbuddy.cn/openapi/v2/authorize')
          and q2.get('response_type') == ['code']
          and q2.get('client_id') == ['cb_YipjG5TEevNZFIblffrL']
          and q2.get('redirect_uri') == [REGISTERED]
          and bool(q2.get('state')), au2[:70])
    check('S9.17 重新授权生成新 state（与旧不同）', q2.get('state', [''])[0] != 'WRONGSTATE')

    check('S9.18 回调页无 JS 报错', not cb_errors, '; '.join(cb_errors[:3]))
    ctx3.close()
    browser.close()

print()
fails = [n for ok, n in results if not ok]
print(f'TOTAL={len(results)}  PASS={len(results)-len(fails)}  FAIL={len(fails)}')
if fails:
    print('FAILED:')
    for n in fails: print('  -', n)
print('OVERALL:', 'FAIL' if fails else 'PASS')
sys.exit(1 if fails else 0)
