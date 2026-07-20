import fs from "node:fs";
import path from "node:path";
import { chromium } from "../xmov-digital-human-web-demos/node_modules/playwright/index.mjs";

const root = path.resolve(import.meta.dirname, "..");
const outputDir = path.join(root, "deliverables", "manual-assets");
const visitorUrl = process.env.VISITOR_URL || "https://139.159.150.134:20443/";
const adminUrl = process.env.ADMIN_URL || "https://139.159.150.134:20444";
const adminUsername = process.env.ADMIN_USERNAME || "admin";
const adminPassword = process.env.ADMIN_PASSWORD || "";

fs.mkdirSync(outputDir, { recursive: true });

const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.CHROME_PATH || "/usr/bin/google-chrome",
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--autoplay-policy=no-user-gesture-required"],
});

async function screenshot(page, name, options = {}) {
  await page.screenshot({
    path: path.join(outputDir, name),
    animations: "disabled",
    ...options,
  });
  process.stdout.write(`captured ${name}\n`);
}

function reportBrowserErrors(page, label) {
  page.on("pageerror", (error) => process.stderr.write(`[${label}] page error: ${error.message}\n`));
  page.on("console", (message) => {
    if (message.type() === "error") {
      process.stderr.write(`[${label}] console error: ${message.text()}\n`);
    }
  });
}

try {
  const visitor = await browser.newPage({
    viewport: { width: 1600, height: 1000 },
    deviceScaleFactor: 1,
    ignoreHTTPSErrors: true,
  });
  reportBrowserErrors(visitor, "visitor");
  await visitor.goto(visitorUrl, { waitUntil: "domcontentloaded", timeout: 60000 });
  await visitor.waitForTimeout(10000);
  await screenshot(visitor, "01-visitor-home.png");

  await visitor.locator('[data-tool-tab="route"]').click();
  await visitor.waitForTimeout(400);
  await screenshot(visitor, "02-visitor-route.png");

  await visitor.locator('[data-tool-tab="location"]').click();
  await visitor.waitForTimeout(400);
  await screenshot(visitor, "03-visitor-location.png");

  await visitor.locator('[data-tool-tab="chat"]').click();
  await visitor.locator("details.advanced-settings").evaluate((element) => {
    element.open = true;
  });
  await visitor.locator("details.feedback").evaluate((element) => {
    element.open = true;
  });
  await visitor.locator("details.feedback").scrollIntoViewIfNeeded();
  await visitor.waitForTimeout(500);
  await screenshot(visitor, "04-visitor-feedback-and-emotion.png");
  await visitor.close();

  if (!adminPassword) {
    throw new Error("ADMIN_PASSWORD is required to capture authenticated admin pages");
  }

  const admin = await browser.newPage({
    viewport: { width: 1600, height: 1000 },
    deviceScaleFactor: 1,
    ignoreHTTPSErrors: true,
  });
  reportBrowserErrors(admin, "admin");
  await admin.goto(`${adminUrl}/login`, { waitUntil: "domcontentloaded", timeout: 60000 });
  await admin.waitForTimeout(500);
  await screenshot(admin, "05-admin-login.png");
  await admin.locator("#username").fill(adminUsername);
  await admin.locator("#password").fill(adminPassword);
  await admin.locator("#submit").click();
  await admin.waitForURL(/\/admin\/?$/, { timeout: 30000 });
  await admin.waitForFunction(
    () => {
      const today = document.querySelector("#todayVisitors")?.textContent?.trim();
      const historical = document.querySelector("#historicalRows")?.textContent?.trim();
      const health = document.querySelector("#healthText")?.textContent || "";
      return today !== "—" && historical !== "—" && !health.includes("检测中");
    },
    { timeout: 30000 },
  ).catch(() => admin.waitForTimeout(1000));
  await screenshot(admin, "06-admin-overview.png");

  await admin.locator('nav button[data-view="knowledge"]').click();
  await admin.waitForTimeout(800);
  await screenshot(admin, "07-admin-knowledge.png");

  const visionCard = admin.locator("#knowledge > .card").nth(1);
  await visionCard.scrollIntoViewIfNeeded();
  await screenshot(admin, "08-admin-vision-library.png");

  await admin.locator('nav button[data-view="avatar"]').click();
  await admin.evaluate(() => window.scrollTo(0, 0));
  await admin.waitForTimeout(600);
  await screenshot(admin, "09-admin-avatar.png");

  await admin.locator('nav button[data-view="reports"]').click();
  await admin.evaluate(() => window.scrollTo(0, 0));
  await admin.waitForTimeout(1200);
  await screenshot(admin, "10-admin-reports.png");

  const historicalCard = admin.locator("#reports > .card").last();
  await historicalCard.scrollIntoViewIfNeeded();
  await admin.waitForTimeout(300);
  await screenshot(admin, "11-admin-historical-data.png");
  await admin.close();
} finally {
  await browser.close();
}
