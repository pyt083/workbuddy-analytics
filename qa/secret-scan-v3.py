#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QA 独立 Secret 扫描（software-qa-engineer-3）
对全仓（排除 .git / node_modules）做多形态扫描：
  - 明文（部分与完整）
  - base64（标准 / 去填充 / 分段混淆）
  - 反转字符串及其 base64
  - hex 编码
  - 大小写变换
另扫 git 历史（所有 commit 的所有 blob）。

⚠ 2026-09-30 P1-1 修复：本文件原以内置分段字面量构造 secret（可被人还原，等于泄漏）。
现改为从仓库外读取，与 tests/secret-scan.js 同一口径：
  环境变量 WB_SCAN_SECRET，或 ~/wb-secret.txt（单行，勿加引号，仓库外文件）。
"""
import base64, os, subprocess, sys, re

ROOT = os.environ.get('WB_SCAN_ROOT', '/Users/donson/WorkBuddy/2026-09-29-23-19-56/workbuddy-analytics')

def _load_secret():
    v = os.environ.get('WB_SCAN_SECRET', '').strip()
    if v:
        return v
    f = os.path.expanduser('~/wb-secret.txt')
    if os.path.exists(f):
        v = open(f, encoding='utf-8').read().strip()
        if v:
            return v
    return None

FULL = _load_secret()
if not FULL:
    print('未提供 secret：请设置环境变量 WB_SCAN_SECRET，或创建 ~/wb-secret.txt（单行，不含引号）。')
    print('示例：echo "YOUR_CLIENT_SECRET" > ~/wb-secret.txt && python3 qa/secret-scan-v3.py')
    sys.exit(2)
PARTS = [FULL[:max(4, len(FULL) // 2)], FULL[max(4, len(FULL) // 2):], FULL]  # 前半 / 后半 / 完整（部分泄漏也能检出）

SKIP_DIRS = {'.git', 'node_modules'}

def b64s(s): return base64.b64encode(s.encode()).decode()
def hexs(s): return s.encode().hex()

needles = {}
for p in PARTS:
    needles['plain:'+p] = p.encode()
    needles['lower:'+p] = p.lower().encode()
    needles['upper:'+p] = p.upper().encode()
    needles['rev:'+p] = p[::-1].encode()
    needles['b64:'+p] = b64s(p).encode()
    needles['b64_nopad:'+p] = b64s(p).rstrip('=').encode()
    needles['b64_rev:'+p] = b64s(p[::-1]).encode()
    needles['hex:'+p] = hexs(p).encode()
    needles['hex_upper:'+p] = hexs(p).upper().encode()

offenders = {}
nfiles = 0

def scan_bytes(path, blob):
    for tag, nd in needles.items():
        if nd in blob:
            offenders.setdefault(path, []).append(tag)

for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
    for fn in filenames:
        p = os.path.join(dirpath, fn)
        if os.path.abspath(p) == os.path.abspath(__file__):
            continue  # 排除扫描工具自身
        try:
            with open(p, 'rb') as f:
                blob = f.read()
        except OSError:
            continue
        nfiles += 1
        scan_bytes(p, blob)

# git 历史 blob 扫描（仓库对象库）
git_hits = []
try:
    out = subprocess.run(['git', '-C', ROOT, 'rev-list', '--all'],
                        capture_output=True, text=True, timeout=60)
    commits = out.stdout.split()
    seen = set()
    for c in commits:
        out2 = subprocess.run(['git', '-C', ROOT, 'ls-tree', '-r', c],
                              capture_output=True, text=True, timeout=30)
        for line in out2.stdout.splitlines():
            meta, path = line.split('\t', 1)
            sha = meta.split()[2]
            if sha in seen: continue
            seen.add(sha)
            blob = subprocess.run(['git', '-C', ROOT, 'cat-file', 'blob', sha],
                                  capture_output=True, timeout=30).stdout
            for tag, nd in needles.items():
                if nd in blob:
                    git_hits.append((c[:8], path, tag))
except Exception as e:
    print('git scan error:', e)

print(f'scanned files: {nfiles} (worktree, excluding .git/node_modules)')
print(f'git commits scanned: {len(commits)}, unique blobs: {len(seen)}')
if offenders:
    print('WORKTREE OFFENDERS:')
    for p, tags in offenders.items():
        print(' ', p, '->', tags)
if git_hits:
    print('GIT HISTORY OFFENDERS:')
    for h in git_hits:
        print(' ', h)
if not offenders and not git_hits:
    print('SECRET SCAN: CLEAN (0 hits across all variants)')
    sys.exit(0)
sys.exit(1)
