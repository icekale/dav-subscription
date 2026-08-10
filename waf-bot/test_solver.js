const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const path = require("node:path");
const test = require("node:test");

const solver = path.join(__dirname, "solver.js");

function run(html, url = "https://xueqiu.com/") {
  return spawnSync(process.execPath, [solver], {
    input: JSON.stringify({
      html,
      url,
      user_agent: "test-agent",
    }),
    encoding: "utf8",
    timeout: 7000,
  });
}

test("executes the complete HTML and captures navigation", () => {
  const html = `<!doctype html><html><body>
    <div id="required-marker">full-dom-marker</div>
    <script>
      if (document.documentElement.innerHTML.includes("full-dom-marker")) {
        location.href = "/signed?md5__1038=test";
      }
    </script>
  </body></html>`;

  const result = run(html);

  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(JSON.parse(result.stdout), {
    signed_url: "https://xueqiu.com/signed?md5__1038=test",
  });
});

test("terminates after page code replaces close and starts an interval", () => {
  const html = `<!doctype html><html><body><script>
    window.close = () => {};
    setInterval(() => {}, 10);
    location.href = "/signed?md5__1038=lifecycle";
  </script></body></html>`;

  const result = run(html);

  assert.equal(result.status, 0, result.error?.message || result.stderr);
  assert.deepEqual(JSON.parse(result.stdout), {
    signed_url: "https://xueqiu.com/signed?md5__1038=lifecycle",
  });
});

test("captures only the first qualifying top-level navigation", () => {
  const html = `<!doctype html><html><body><script>
    location.href = "https://example.com/foreign?md5__1038=wrong";
    const frame = document.createElement("iframe");
    document.body.appendChild(frame);
    frame.contentWindow.location.href = "/frame?md5__1038=wrong";
    location.href = "/signed?md5__1038=intended";
    location.href = "/later?md5__1038=wrong";
    location.href = "/unsigned";
  </script></body></html>`;

  const result = run(html);

  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(JSON.parse(result.stdout), {
    signed_url: "https://xueqiu.com/signed?md5__1038=intended",
  });
});

test("fails when the page produces no navigation", () => {
  const result = run("<!doctype html><html><body>no challenge</body></html>");

  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /signed URL/i);
});

test("reports a malformed base URL without a stack trace", () => {
  const result = run("<!doctype html><html></html>", "://bad");

  assert.notEqual(result.status, 0);
  assert.equal(result.stderr, "invalid URL\n");
});
