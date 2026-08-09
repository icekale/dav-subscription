const test = require("node:test");
const assert = require("node:assert");
const { recordTap, WINDOW_MS, TRIGGER_COUNT } = require("../../app/static/vendor/taps.js");

test("窗口内连点达到阈值触发", () => {
  let s = null;
  s = recordTap(s, 1000);
  s = recordTap(s, 1100);
  const r = recordTap(s, 1200);
  assert.strictEqual(r.triggered, true);
  assert.strictEqual(r.count, TRIGGER_COUNT);
});

test("连点不足阈值不触发", () => {
  let s = null;
  s = recordTap(s, 1000);
  const r = recordTap(s, 1100);
  assert.strictEqual(r.triggered, false);
});

test("窗口外点击清零重新计数", () => {
  let s = null;
  s = recordTap(s, 1000);
  s = recordTap(s, 1100);
  const r = recordTap(s, s.last + WINDOW_MS + 1);
  assert.strictEqual(r.triggered, false);
  assert.strictEqual(r.count, 1);
});
