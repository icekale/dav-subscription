# Xueqiu WAF jsdom Solver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Playwright/Chromium waf-bot with a Python + Node/jsdom solver that only publishes cookies after a real Xueqiu timeline probe succeeds.

**Architecture:** Python keeps ownership of the curl_cffi session, seed cookies, retries, validation, and atomic JSON output. A small Node process receives the complete challenge HTML over stdin, executes it with pinned jsdom, and returns the captured signed navigation URL. The existing main-service cookie-file contract remains unchanged.

**Tech Stack:** Python 3.12, curl_cffi 0.16.0, Node.js 22, jsdom 29.1.1, whatwg-url 16.0.1, pytest, Node built-in test runner, Docker Compose.

---

## File Map

- Create `waf-bot/solver.js`: execute complete challenge HTML and return the signed navigation URL.
- Create `waf-bot/test_solver.js`: deterministic synthetic-page tests for the Node solver.
- Create `waf-bot/package.json`: pin jsdom and whatwg-url and expose the Node test command.
- Create `waf-bot/package-lock.json`: lock the tested dependency graph.
- Create `waf-bot/test_watchdog.py`: Python unit tests for challenge flow, validation, seed cookies, and output preservation.
- Modify `waf-bot/watchdog.py`: replace Playwright with curl_cffi plus the Node solver.
- Modify `waf-bot/Dockerfile`: remove Chromium and install the pinned Python/Node dependencies.
- Modify `docker-compose.unraid.yml`: remove the obsolete Playwright mirror argument and browser wording.
- Modify `docker-compose.prod.yml`: update the waf-bot description.
- Modify `README.md`: document the Chromium-free solver and troubleshooting behavior.
- Modify `app/fetchers/xueqiu.py`: update stale browser-specific comments only; behavior stays unchanged.

### Task 1: Add the Complete-HTML jsdom Solver

**Files:**
- Create: `waf-bot/test_solver.js`
- Create: `waf-bot/solver.js`
- Create: `waf-bot/package.json`
- Create: `waf-bot/package-lock.json`

- [ ] **Step 1: Add the package manifest**

Create `waf-bot/package.json`:

```json
{
  "name": "dav-waf-bot",
  "private": true,
  "version": "1.0.0",
  "scripts": {
    "test": "node --test test_solver.js"
  },
  "dependencies": {
    "jsdom": "29.1.1",
    "whatwg-url": "16.0.1"
  }
}
```

Generate the lockfile without installing browser software:

```bash
cd waf-bot
npm install --package-lock-only --ignore-scripts
```

Expected: `package-lock.json` pins jsdom 29.1.1 and whatwg-url 16.0.1.

- [ ] **Step 2: Write the failing Node test**

Create `waf-bot/test_solver.js`:

```javascript
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
```

- [ ] **Step 3: Run the Node test to verify RED**

Run:

```bash
cd waf-bot
npm install --ignore-scripts
npm test
```

Expected: FAIL because `solver.js` does not exist.

- [ ] **Step 4: Implement the minimal solver**

Create `waf-bot/solver.js` with these behaviors:

```javascript
#!/usr/bin/env node
const fs = require("node:fs");
const path = require("node:path");
const { serializeURL } = require("whatwg-url");

const jsdomRoot = path.dirname(require.resolve("jsdom/package.json"));
const navigation = require(path.join(jsdomRoot, "lib/jsdom/living/window/navigation.js"));
let signedUrl = "";
navigation.navigate = (_window, newURL) => {
  signedUrl = newURL ? serializeURL(newURL) : "";
};

const { JSDOM, VirtualConsole } = require("jsdom");

function fail(message) {
  process.stderr.write(`${message}\n`);
  process.exit(1);
}

let input;
try {
  input = JSON.parse(fs.readFileSync(0, "utf8"));
} catch (error) {
  fail(`invalid input: ${error.message}`);
}
if (!input.html || !input.url || !input.user_agent) fail("invalid input fields");

const virtualConsole = new VirtualConsole();
const dom = new JSDOM(input.html, {
  url: input.url,
  runScripts: "dangerously",
  pretendToBeVisual: true,
  virtualConsole,
  beforeParse(window) {
    Object.defineProperty(window.navigator, "userAgent", {
      value: input.user_agent,
    });
  },
});

setTimeout(() => {
  dom.window.close();
  if (!signedUrl) fail("signed URL was not produced");
  process.stdout.write(`${JSON.stringify({ signed_url: signedUrl })}\n`);
}, 5000);
```

Do not enable jsdom resource loading or expose Node `require` to page scripts.

- [ ] **Step 5: Run the Node tests to verify GREEN**

Run:

```bash
cd waf-bot
npm test
```

Expected: 2 tests pass, 0 fail.

- [ ] **Step 6: Commit the solver**

```bash
git add waf-bot/solver.js waf-bot/test_solver.js waf-bot/package.json waf-bot/package-lock.json
git commit -m "feat(waf-bot): solve Xueqiu challenge with jsdom"
```

### Task 2: Rewrite the Python Watchdog Around curl_cffi

**Files:**
- Create: `waf-bot/test_watchdog.py`
- Modify: `waf-bot/watchdog.py`

- [ ] **Step 1: Write the failing watchdog tests**

Create `waf-bot/test_watchdog.py`. Load the sibling module normally and define small real fakes for the HTTP boundary:

```python
import json
from pathlib import Path

import watchdog


class FakeCookies:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def set(self, name, value, **_kwargs):
        self.values[name] = value

    def get_dict(self):
        return dict(self.values)


class FakeResponse:
    def __init__(self, status_code=200, text="", payload=None, content_type="text/html"):
        self.status_code = status_code
        self.text = text
        self._payload = payload
        self.headers = {"content-type": content_type}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, responses, cookies=None):
        self.responses = list(responses)
        self.cookies = FakeCookies(cookies)
        self.calls = []
        self.closed = False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)

    def close(self):
        self.closed = True
```

Add these focused tests:

```python
def target():
    return {
        "url": "https://xueqiu.com/",
        "out": "xueqiu",
        "seed_cookie": "xq_a_token=seed; u=7",
    }


def test_refresh_passes_complete_html_to_solver_and_writes_verified_cookies(tmp_path):
    challenge = "<html><textarea id='renderData'>challenge</textarea><div>required DOM</div></html>"
    session = FakeSession(
        [
            FakeResponse(text=challenge),
            FakeResponse(text="<html>雪球</html>"),
            FakeResponse(payload={"statuses": []}, content_type="application/json"),
        ],
        cookies={"acw_tc": "ok"},
    )
    seen = {}

    def solve(html, url):
        seen.update(html=html, url=url)
        return "/?md5__1038=valid"

    output = tmp_path / "cookies.json"
    assert watchdog.refresh(target(), session=session, solve=solve, output=str(output))
    assert seen == {"html": challenge, "url": "https://xueqiu.com/"}
    written = {
        item["name"]: item["value"]
        for item in json.loads(output.read_text())["cookies"]
    }
    assert written == {"xq_a_token": "seed", "u": "7", "acw_tc": "ok"}


def test_refresh_keeps_old_file_when_signed_response_is_still_challenge(tmp_path):
    output = tmp_path / "cookies.json"
    output.write_text("old", encoding="utf-8")
    session = FakeSession([
        FakeResponse(text="<textarea id='renderData'>one</textarea>"),
        FakeResponse(text="<textarea id='renderData'>two</textarea>"),
    ])

    assert not watchdog.refresh(target(), session=session, solve=lambda *_: "/signed", output=str(output))
    assert output.read_text(encoding="utf-8") == "old"


def test_refresh_keeps_old_file_when_probe_is_not_valid_json(tmp_path):
    output = tmp_path / "cookies.json"
    output.write_text("old", encoding="utf-8")
    session = FakeSession([
        FakeResponse(text="<html>雪球</html>"),
        FakeResponse(payload=ValueError("bad json"), content_type="text/html"),
    ], cookies={"acw_tc": "intermediate"})

    assert not watchdog.refresh(target(), session=session, solve=lambda *_: "unused", output=str(output))
    assert output.read_text(encoding="utf-8") == "old"


def test_refresh_injects_seed_cookie_into_session(tmp_path):
    session = FakeSession([
        FakeResponse(text="<html>雪球</html>"),
        FakeResponse(payload={"statuses": []}, content_type="application/json"),
    ])

    assert watchdog.refresh(target(), session=session, solve=lambda *_: "unused", output=str(tmp_path / "cookies.json"))
    assert session.cookies.values["xq_a_token"] == "seed"
    assert session.cookies.values["u"] == "7"
```

- [ ] **Step 2: Run the Python tests to verify RED**

Run:

```bash
cd waf-bot
../../../.venv/bin/python -m pytest test_watchdog.py -q
```

Expected: FAIL because the existing `refresh()` has no injected session/solver/output API and imports Playwright.

- [ ] **Step 3: Implement the minimal curl_cffi watchdog**

Rewrite `waf-bot/watchdog.py` around these constants and helpers:

```python
from pathlib import Path
from urllib.parse import urljoin
import subprocess

from curl_cffi import requests

SOLVER = Path(__file__).with_name("solver.js")
PROBE_URL = "https://xueqiu.com/statuses/user_timeline.json"
PROBE_PARAMS = {"user_id": "1247347556", "page": 1, "count": 1}


def _is_challenge(response) -> bool:
    return "text/html" in response.headers.get("content-type", "") and "renderData" in response.text


def _solve_challenge(html: str, url: str) -> str:
    result = subprocess.run(
        ["node", str(SOLVER)],
        input=json.dumps({"html": html, "url": url, "user_agent": UA}),
        text=True,
        capture_output=True,
        timeout=10,
        check=True,
    )
    signed = (json.loads(result.stdout).get("signed_url") or "").strip()
    if not signed:
        raise RuntimeError("WAF solver did not return a signed URL")
    return signed
```

Use this refresh signature so tests can inject only the two external boundaries:

```python
def refresh(target: dict, *, session=None, solve=_solve_challenge, output: str | None = None) -> bool:
```

Behavior inside `refresh()`:

1. Create `requests.Session(impersonate="chrome124")` only when `session` is not supplied.
2. Inject seed cookies with `session.cookies.set(name, value, domain=".xueqiu.com", path="/")`.
3. GET the target homepage with browser navigation headers and a 30-second timeout.
4. If challenged, call `solve(response.text, target["url"])`, normalize with `urljoin`, and GET the signed URL in the same session with the original URL as Referer.
5. Return `False` if the signed response is still a challenge.
6. GET `PROBE_URL` with `PROBE_PARAMS` and JSON/XHR headers.
7. Require status 200 and a JSON dict containing a list-valued `statuses` key.
8. Convert `session.cookies.get_dict()` to the existing list of `{name, value}` objects in insertion order.
9. Write a temporary JSON file and atomically replace `output or OUTPUT` only after every validation passes.
10. Catch request, subprocess, JSON, and filesystem errors at the refresh boundary, print a short stage message, and return `False` without exposing cookies or the full signed URL.
11. Close only sessions created inside `refresh()`.

Remove Playwright, browser sleeps, selector checks, and the unused generic-target claims from the module docstring.

- [ ] **Step 4: Run the Python tests to verify GREEN**

Run:

```bash
cd waf-bot
../../../.venv/bin/python -m pytest test_watchdog.py -q
```

Expected: 4 tests pass, 0 fail.

- [ ] **Step 5: Run the Node and Python waf-bot tests together**

Run:

```bash
cd waf-bot
npm test
../../../.venv/bin/python -m pytest test_watchdog.py -q
```

Expected: all solver and watchdog tests pass.

- [ ] **Step 6: Commit the watchdog rewrite**

```bash
git add waf-bot/watchdog.py waf-bot/test_watchdog.py
git commit -m "feat(waf-bot): validate jsdom WAF sessions"
```

### Task 3: Remove Chromium From the Image and Update Documentation

**Files:**
- Modify: `waf-bot/Dockerfile`
- Modify: `docker-compose.unraid.yml`
- Modify: `docker-compose.prod.yml`
- Modify: `README.md`
- Modify: `app/fetchers/xueqiu.py`

- [ ] **Step 1: Write a failing image-policy check**

Run before editing:

```bash
rg -n "playwright|chromium|PLAYWRIGHT_DOWNLOAD_HOST" waf-bot/Dockerfile docker-compose.unraid.yml README.md
```

Expected: matches are present, proving the old browser dependency and documentation still exist.

- [ ] **Step 2: Replace the Dockerfile**

Use a Node stage only as the source of the Node runtime, then keep the Python 3.12 runtime:

```dockerfile
FROM node:22-bookworm-slim AS node
FROM python:3.12-slim-bookworm

WORKDIR /app
ARG PIP_INDEX_URL=https://pypi.org/simple

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && \
    ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

COPY package.json package-lock.json /app/
RUN npm ci --omit=dev --ignore-scripts && \
    pip install --no-cache-dir -i ${PIP_INDEX_URL} --retries 5 --timeout 60 curl_cffi==0.16.0

COPY solver.js watchdog.py /app/
ENV WAF_COOKIE_FILE=/data/waf_cookies.json
CMD ["python", "/app/watchdog.py"]
```

Do not retain browser libraries, Xvfb, Playwright download arguments, or Chromium installation layers.

- [ ] **Step 3: Update Compose and docs**

- Remove `PLAYWRIGHT_DOWNLOAD_HOST` from `docker-compose.unraid.yml`.
- Change Compose comments from “无头浏览器” to “轻量 JS 求解器”.
- Update the README anti-bot section to say waf-bot uses curl_cffi + jsdom and validates the real timeline API before publishing cookies.
- Update troubleshooting to retain the same container/file commands while removing Chromium wording.
- Update browser-specific comments in `app/fetchers/xueqiu.py` without changing logic.

- [ ] **Step 4: Verify browser dependencies are gone**

Run:

```bash
rg -n "playwright|chromium|PLAYWRIGHT_DOWNLOAD_HOST" waf-bot docker-compose.unraid.yml docker-compose.prod.yml README.md app/fetchers/xueqiu.py
```

Expected: no runtime or documentation matches. Historical design/findings documents may still mention Chromium for context and are excluded from this command.

- [ ] **Step 5: Run focused and full Python checks**

Run:

```bash
cd waf-bot
npm test
../../../.venv/bin/python -m pytest test_watchdog.py -q
cd ..
../../.venv/bin/python -m pytest -q
../../.venv/bin/ruff check waf-bot/watchdog.py waf-bot/test_watchdog.py app/fetchers/xueqiu.py
```

Expected: Node tests pass, watchdog tests pass, the full existing suite passes, and ruff reports no errors.

- [ ] **Step 6: Build the new waf-bot image**

Run:

```bash
docker build -t dav-waf-bot:jsdom-test waf-bot
```

Expected: build succeeds without downloading Chromium or Playwright.

Inspect the image:

```bash
docker run --rm dav-waf-bot:jsdom-test node --version
docker run --rm dav-waf-bot:jsdom-test python -c "import curl_cffi; print(curl_cffi.__version__)"
```

Expected: Node 22.x and curl_cffi 0.16.0.

- [ ] **Step 7: Commit container and documentation changes**

```bash
git add waf-bot/Dockerfile docker-compose.unraid.yml docker-compose.prod.yml README.md app/fetchers/xueqiu.py
git commit -m "build(waf-bot): remove Chromium runtime"
```

### Task 4: Online Smoke Test and Final Verification

**Files:**
- No production files expected unless verification exposes a defect.

- [ ] **Step 1: Run a one-shot refresh in the built image**

Use an isolated output directory and a bounded process:

```bash
mkdir -p /tmp/dav-waf-smoke

docker run --rm \
  -e WAF_COOKIE_FILE=/data/waf_cookies.json \
  -e WAF_REFRESH_INTERVAL=3600 \
  -v /tmp/dav-waf-smoke:/data \
  dav-waf-bot:jsdom-test \
  python -c "import watchdog; print(watchdog.refresh(watchdog.TARGETS[0]))"
```

Expected: prints `True` and creates `/tmp/dav-waf-smoke/waf_cookies.json`.

- [ ] **Step 2: Validate the smoke-test cookie file without printing secrets**

Run:

```bash
python -c "import json; d=json.load(open('/tmp/dav-waf-smoke/waf_cookies.json')); print(bool(d.get('cookies')), sorted(c['name'] for c in d['cookies']))"
```

Expected: `True` and names including `acw_tc`, `xq_a_token`, and `xqat`; no values are printed.

- [ ] **Step 3: Run final repository verification**

Run:

```bash
cd waf-bot
npm test
../../../.venv/bin/python -m pytest test_watchdog.py -q
cd ..
../../.venv/bin/python -m pytest -q
../../.venv/bin/ruff check .
git diff --check
git status --short
```

Expected: all tests pass, ruff is clean, diff check is clean, and only intended committed changes exist.

- [ ] **Step 4: Record verification evidence in the final response**

Report:

- Node solver test count.
- Watchdog test count.
- Full pytest count.
- Docker image build result.
- Online refresh result without cookie values.
- Final commit hashes and any remaining external-WAF risk.
