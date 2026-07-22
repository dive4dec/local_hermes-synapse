# CHANGE: moodle-auto-download 从 Selenium 转为 CDP attach 模式

日期: 2026-07-17
文件: /var/www/moodledata/.hermes/skills/moodle-auto-download/moodle_quiz_downloader_tool.py
备份: moodle_quiz_downloader_tool.py.selenium.bak (旧 Selenium 版本，可回滚)

## 背景与动机
原工具用 Selenium + chromedriver 自己启动浏览器，并用 --username/--password
在登录页提交表单。存在两个问题:
1. 安全性: 账号密码进入脚本参数、命令行历史、cron 配置。
2. 版本脆弱: chromedriver 必须与浏览器大版本匹配。被控浏览器在用户本机
   (Chrome 149) 且会自动更新，容器内的 chromedriver (Alpine apk 锁定 131)
   无法匹配 —— Selenium attach 模式仍走 chromedriver，会被拒 (only supports
   Chrome version 131)。Alpine 是 musl，装 glibc 的官方 chromedriver 149 不可行。

## 方案: 纯 CDP，接管已登录浏览器
不再启动浏览器、不再登录。脚本通过 Chrome DevTools Protocol (CDP) 连接到一个
用户已经打开并已登录 Moodle 的浏览器实例 (--remote-debugging-port)，复用其
会话 cookie。CDP 是版本无关的 WebSocket 协议，绕过 chromedriver，本机浏览器
升级到任何版本都不受影响。凭据不再进入脚本。

## 具体改动
- 删除 Selenium / webdriver-manager / chromedriver 依赖。
- 新增轻量 CDPSession 类 (requests + websocket-client):
  * 通过 HTTP /json/version 校验端点并打印浏览器版本。
  * 通过 /json/new 开一个**独立 tab** 操作，绝不干扰用户当前 tab。
  * navigate = Page.navigate + 轮询 document.readyState。
  * evaluate = Runtime.evaluate (returnByValue) 跑 JS 返回 JSON。
  * print_to_pdf = Page.printToPDF (原本就是 CDP)。
  * close() 只关自己开的 tab，**从不 quit 浏览器** (属于用户)。
- 所有 Selenium find_elements/.text/.get_attribute 改写为 CDP + JS (querySelectorAll)。
- login() 整块删除，替换为 verify_logged_in(): 访问 /my/，若被重定向到
  login/index.php 则明确报错提示用户先在浏览器登录。
- CLI: 移除 --username/--password/--headed，新增 --debugger-address
  (默认 127.0.0.1:9222)。其余 flag (--course-identifier / --high|medium|low-quantity
  / --keywords / --exact-quiz-name / --output-dir / --no-download) 完全保留。
- 业务逻辑 (course 解析、分页 all_with 抓 attempt、逐 attempt 读权威成绩、
  采样算法 High/Medium/Low、文件命名) **一字未改**。

## 两个真实环境的坑 (已在本容器验证并修复)
1. WebSocket Origin 拒绝: 新版 Chrome 对 DevTools WS 握手校验 Origin 头，
   返回 403 "Use --remote-allow-origins"。修复: create_connection(...,
   suppress_origin=True) 不发 Origin 头，Chrome 放行 —— 用户无需加
   --remote-allow-origins 启动浏览器。
2. Host 头限制 (网络接管场景): Chrome 只接受 Host 为 localhost/IP 的调试请求。
   容器跨网络连本机时不能直接连 host-ip:9222，需在容器内用 socat 监听
   127.0.0.1:9222 转发到本机，握手 Host 头才是 localhost。

## 连接配方 (本机浏览器 + 容器接管)
1. 本机: chrome --remote-debugging-port=9222，登录 Moodle。
2. 让容器可达本机端口 (socat / SSH 转发)。容器内:
   socat TCP-LISTEN:9222,bind=127.0.0.1,fork TCP:<本机>:9222
3. 运行:
   python3 moodle_quiz_downloader_tool.py \
     --debugger-address 127.0.0.1:9222 \
     --moodle-url https://deep.cs.cityu.edu.hk/equiz \
     --course-identifier "CS2310" \
     --high-quantity 5 --medium-quantity 5 --low-quantity 5 \
     --keywords "iRAT1" --exact-quiz-name \
     --output-dir /var/www/moodledata/.hermes/cron/output/

## 验证结果 (2026-07-17)
在本 Alpine 容器内起 headless chromium 131 --remote-debugging-port=9222，
CDPSession 全链路通过: 连接 / 开独立 tab / 导航 / evaluate 读文本与链接 /
Page.printToPDF 生成真实 PDF (%PDF- 魔数, 12KB) / 用完关闭自己 tab 且浏览器
tab 数不变。CLI --help 与无浏览器时的错误提示均正常。

## 回滚
cp moodle_quiz_downloader_tool.py.selenium.bak moodle_quiz_downloader_tool.py
并恢复 requirements.txt 的 selenium/webdriver-manager 行。
