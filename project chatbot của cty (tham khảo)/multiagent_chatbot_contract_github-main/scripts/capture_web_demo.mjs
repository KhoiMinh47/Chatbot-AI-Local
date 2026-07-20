import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
let playwright;
try {
  playwright = require("playwright");
} catch {
  playwright = require("../.runtime/playwright/node_modules/playwright");
}
const { chromium } = playwright;

const rootDir = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const envPath = path.join(rootDir, ".env");
const outDir = path.join(rootDir, "docs", "assets", "web-demo-frames");
const screenshotPath = path.join(rootDir, "docs", "assets", "rag-chat-web-response.png");

function readEnv(filePath) {
  const data = {};
  const text = fs.readFileSync(filePath, "utf8");
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) continue;
    const index = trimmed.indexOf("=");
    data[trimmed.slice(0, index)] = trimmed.slice(index + 1);
  }
  return data;
}

async function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function capture(page, index) {
  const name = String(index).padStart(3, "0");
  await page.screenshot({ path: path.join(outDir, `frame-${name}.png`), fullPage: false });
}

const env = readEnv(envPath);
const email = env.ROOT_EMAIL;
const password = env.ROOT_PASSWORD;
const baseUrl = "http://127.0.0.1:3000";

fs.rmSync(outDir, { recursive: true, force: true });
fs.mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 1 });

let frame = 0;
await page.goto(`${baseUrl}/signin`, { waitUntil: "networkidle" });
await capture(page, frame++);
await page.fill('input[type="email"]', email);
await page.fill('input[type="password"]', password);
await capture(page, frame++);
await page.click('button[type="submit"]');
await page.waitForURL(/\/chat/, { timeout: 30000 });
await page.waitForLoadState("networkidle");

for (let i = 0; i < 4; i += 1) {
  await wait(500);
  await capture(page, frame++);
}

const prompt = "Kiểm tra nhanh: hệ thống RAG/vLLM đang hoạt động bình thường chứ? Trả lời ngắn gọn.";
const textarea = page.locator("textarea").last();
await textarea.fill(prompt);
await capture(page, frame++);
await page.keyboard.press("Enter");

for (let i = 0; i < 24; i += 1) {
  await wait(1000);
  await capture(page, frame++);
  const text = await page.locator("body").innerText();
  if (/hoạt động|bình thường|đang hoạt động|RAG|vLLM/i.test(text) && i >= 5) {
    break;
  }
}

await page.screenshot({ path: screenshotPath, fullPage: false });
await browser.close();

console.log(JSON.stringify({ frames: frame, screenshotPath, outDir }, null, 2));
