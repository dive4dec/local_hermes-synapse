#!/bin/bash

# 確保腳本在遇到錯誤時立即停止執行
set -e

echo "=== 開始安裝系統依賴 ==="

# 1. 安裝 Chromium 瀏覽器 (解決環境中 Chromium 缺失的問題)
# 這裡假設您的 Pod 運行環境是基於 Debian/Ubuntu
echo "正在更新系統套件列表並安裝 Chromium..."
apt-get update
apt-get install -y chromium

# 2. 安裝 Python 依賴套件
echo "正在安裝 requirements.txt 中的 Python 依賴..."
# 安裝 requests 與 websocket-client 套件[cite: 1]
pip install -r requirements.txt

echo "=== 所有依賴安裝完成！ ==="