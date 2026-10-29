#!/bin/bash
# WorkBuddy 数据分析平台 — Firebase 后端一键部署脚本
# 用法：在本项目目录下执行  ./deploy-firebase.sh
# 说明：会在浏览器完成 Google 登录，然后交互式让你粘贴 Client Secret，最后部署函数与规则。
set -euo pipefail

cd "$(dirname "$0")"

echo "== 1/4 登录 Firebase（浏览器会打开，用你创建项目的 Google 账号登录）=="
firebase login

echo "== 2/4 选择/绑定 Firebase 项目 =="
if [ ! -f .firebaserc ]; then
  firebase use --add
else
  echo "已绑定项目：$(cat .firebaserc)"
fi

echo "== 3/4 写入 Client Secret 到 Secret Manager =="
echo "   提示出现后粘贴你的 WorkBuddy Client Secret（cb_ 应用的 sk_live_ 开头密钥，见开放平台应用详情页；不进代码仓库）"
firebase functions:secrets:set WB_CLIENT_SECRET

echo "== 4/4 部署 Cloud Functions 与 Firestore 安全规则 =="
firebase deploy --only functions,firestore:rules

echo "== 完成 =="
echo "下一步：打开 https://pyt083.github.io/workbuddy-analytics/ 登录后在『数据源』切换到 API 真实数据并授权。"
