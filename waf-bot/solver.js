#!/usr/bin/env node
const fs = require("node:fs");
const path = require("node:path");
const { serializeURL } = require("whatwg-url");

const jsdomRoot = path.dirname(require.resolve("jsdom/package.json"));
const navigation = require(path.join(jsdomRoot, "lib/jsdom/living/window/navigation.js"));
let baseOrigin = "";
let navigationError;
let signedUrl = "";
navigation.navigate = (window, newURL) => {
  if (signedUrl || !newURL) return;

  try {
    if (window !== window.top) return;
    const candidate = serializeURL(newURL);
    const url = new URL(candidate);
    if (url.origin === baseOrigin && url.searchParams.has("md5__1038")) {
      signedUrl = candidate;
    }
  } catch (error) {
    navigationError = error;
  }
};

const { JSDOM, VirtualConsole } = require("jsdom");

function fail(message) {
  fs.writeSync(2, `${message}\n`);
  process.exit(1);
}

let input;
try {
  input = JSON.parse(fs.readFileSync(0, "utf8"));
} catch (error) {
  fail(`invalid input: ${error.message}`);
}

if (
  !input ||
  typeof input.html !== "string" ||
  !input.html ||
  typeof input.url !== "string" ||
  !input.url ||
  typeof input.user_agent !== "string" ||
  !input.user_agent
) {
  fail("invalid input fields");
}

try {
  baseOrigin = new URL(input.url).origin;
} catch {
  fail("invalid URL");
}

const virtualConsole = new VirtualConsole();
let closeWindow;
try {
  new JSDOM(input.html, {
    url: input.url,
    runScripts: "dangerously",
    pretendToBeVisual: true,
    virtualConsole,
    beforeParse(window) {
      closeWindow = window.close.bind(window);
      Object.defineProperty(window.navigator, "userAgent", {
        value: input.user_agent,
      });
    },
  });
} catch (error) {
  fail(`solver failed: ${error.message}`);
}

setTimeout(() => {
  try {
    closeWindow();
  } catch {
    // Cleanup is best-effort; explicit process exit below is authoritative.
  }

  if (!signedUrl) {
    if (navigationError) fail(`navigation failed: ${navigationError.message}`);
    fail("signed URL was not produced");
  }

  fs.writeSync(1, `${JSON.stringify({ signed_url: signedUrl })}\n`);
  process.exit(0);
}, 5000);
