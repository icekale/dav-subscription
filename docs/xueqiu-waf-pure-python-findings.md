# 雪球 WAF 纯 Python 逆向可行性探索（结论：不可行）

2026-08-10 在 `feat/xueqiu-waf-pure-python` 分支做的探索。目标：用轻量 JS 引擎（quickjs/jsdom）替代 waf-bot 的 200MB Chromium，纯 Python 算出雪球 WAF 通关 cookie。

## 结论

**纯 Python 路线不可行。** waf-bot（headless Chromium）是唯一可行解。

## 探索过程与关键证据

1. **挑战页结构分析**（`v4/` 路径可稳定拿到 200 挑战页）：
   - `renderData` textarea 存挑战值 `_waf_bd8ce2ce37`
   - script 0：读 renderData → `window._waf_*`
   - script 2（75KB）：主算法，**无 canvas/WebGL/navigator 等环境指纹 API**（统计为 0），看似纯 JS 计算
   - 自校验：script 从 DOM 里找 `<script name="aliyunwaf_6a6f5ea8">`（即自身 textContent）参与计算

2. **quickjs 执行**：缺大量 DOM stub（`not a function`），无法独立跑通。

3. **jsdom 执行**：补 DOM stub 后可完整执行，算出**与真浏览器同格式**的签名 URL（`md5__1038=2790552d-...`）。关键点：patch jsdom `navigation.js` 的 `navigate()` 必须在 `require('jsdom')` 之前（Location-impl 加载时解构引用）。

4. **决定性反证**：jsdom 算出的签名 URL，用**真实 chromium 直接访问也 400**（非 TLS 指纹问题，指纹对）。说明服务端签名验证绑定了真浏览器环境的更多特征（疑为 TLS/HTTP2 指纹哈希参与签名计算，或挑战值/会话绑定）。

## 技术要点（留档备查）

- 挑战流程：无 cookie → 挑战页(Set-Cookie acw_tc) → JS 计算 → `location` 跳转签名 URL → 服务端验证 → Set-Cookie acw_tc(放行) + 返回数据
- 真浏览器签名请求 cookie 为空（acw_tc 不参与签名请求，但首次挑战页的 acw_tc 需在 jar 里）
- 签名 URL 与 renderData 必须同页配对（每次请求 renderData 都变）
- 冒烟验证工具：`/tmp/xq_full_flow_v7.js`（node + jsdom 全链路）、`/tmp/xq_capture_signed2.js`（算签名）、`/tmp/xq_replay_signed.py`（curl_cffi 重放）

## 为什么不值得继续

- 即使逆向出算法，雪球/阿里云随时可轮换混淆（脚本每次请求都可能变）
- waf-bot 已稳定运行（时间线 ok=19 / 组合 ok=4），零维护
- 逆向是几天级工程且脆弱，收益（省 200MB 镜像）远低于成本
