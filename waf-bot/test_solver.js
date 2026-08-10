const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const path = require("node:path");
const test = require("node:test");

const solver = path.join(__dirname, "solver.js");

function run(html) {
  return spawnSync(process.execPath, [solver], {
    input: JSON.stringify({
      html,
      url: "https://xueqiu.com/",
      user_agent: "test-agent",
    }),
    encoding: "utf8",
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

test("fails when the page produces no navigation", () => {
  const result = run("<!doctype html><html><body>no challenge</body></html>");

  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /signed URL/i);
});
