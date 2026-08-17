# 雪球 WAF 纯 Python 逆向可行性探索（旧结论已推翻）

2026-08-10 在 `feat/xueqiu-waf-pure-python` 分支做的探索。目标：用轻量 JS 引擎（quickjs/jsdom）替代 waf-bot 的 200MB Chromium，纯 Python 算出雪球 WAF 通关 cookie。

> 复验更正：旧 PoC 手工重建了精简 DOM，遗漏了参与签名的完整页面内容。将服务端返回的完整 HTML 原样交给 jsdom 后，签名请求和真实时间线 API 均返回 200。jsdom 路线可行。

## 结论

**“签名绑定真实浏览器环境”的结论不成立。** Python + Node/jsdom 可替代 Chromium；严格 QuickJS 纯 Python 仍需继续对齐运行时能力检测。

## 探索过程与关键证据

1. **挑战页结构分析**（`v4/` 路径可稳定拿到 200 挑战页）：
   - `renderData` textarea 存挑战值 `_waf_bd8ce2ce37`
   - script 0：读 renderData → `window._waf_*`
   - script 2（75KB）：主算法，**无 canvas/WebGL/navigator 等环境指纹 API**（统计为 0），看似纯 JS 计算
   - 自校验：script 从 DOM 里找 `<script name="aliyunwaf_6a6f5ea8">`（即自身 textContent）参与计算

2. **quickjs 执行**：缺大量 DOM stub（`not a function`），无法独立跑通。

3. **jsdom 执行**：补 DOM stub 后可完整执行，算出**与真浏览器同格式**的签名 URL（`md5__1038=2790552d-...`）。关键点：patch jsdom `navigation.js` 的 `navigate()` 必须在 `require('jsdom')` 之前（Location-impl 加载时解构引用）。

4. **当时误判为决定性反证**：精简 DOM 下 jsdom 算出的签名 URL，即使用真实 Chromium 请求也返回 400。当时据此怀疑 TLS/HTTP2 或浏览器环境绑定；后续完整 HTML 复验证明，根因是签名输入中的 DOM 内容不完整。

## 技术要点（留档备查）

- 挑战流程：无 cookie → 挑战页(Set-Cookie acw_tc) → JS 计算 → `location` 跳转签名 URL → 服务端验证 → Set-Cookie acw_tc(放行) + 返回数据
- 真浏览器签名请求 cookie 为空（acw_tc 不参与签名请求，但首次挑战页的 acw_tc 需在 jar 里）
- 签名 URL 与 renderData 必须同页配对（每次请求 renderData 都变）
- 冒烟验证工具：`/tmp/xq_full_flow_v7.js`（node + jsdom 全链路）、`/tmp/xq_capture_signed2.js`（算签名）、`/tmp/xq_replay_signed.py`（curl_cffi 重放）

## 后续方向

- 保留完整挑战 HTML，由固定版本 jsdom 直接执行，不逆向混淆算法。
- Python watchdog 继续负责 curl_cffi 会话、Cookie 验证和原子写文件。
- QuickJS 当前生成无效 `type__0` 参数，不纳入本次无 Chromium 交付范围。
