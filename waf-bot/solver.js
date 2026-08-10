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
