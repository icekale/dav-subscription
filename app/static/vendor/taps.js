// 点击计数：窗口内连续点击达到阈值即触发。纯函数，便于测试。
// UMD：浏览器挂全局 TapCounter，Node 环境走 CommonJS 导出。
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.TapCounter = factory();
})(typeof self !== "undefined" ? self : this, function () {
  const WINDOW_MS = 2000;
  const TRIGGER_COUNT = 3;

  // state: { count, last }；now 为毫秒时间戳
  function recordTap(state, now) {
    const s = state || { count: 0, last: 0 };
    const count = now - s.last > WINDOW_MS ? 1 : s.count + 1;
    return { count, last: now, triggered: count >= TRIGGER_COUNT };
  }

  return { recordTap, WINDOW_MS, TRIGGER_COUNT };
});
