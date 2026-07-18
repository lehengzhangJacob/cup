import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, "..");
const workDir = path.join(projectRoot, "output", "video-work");
const rawDir = path.join(workDir, "raw");
const manifestPath = path.join(workDir, "studybridge-narration-manifest.json");
const viewport = { width: 1600, height: 1000 };

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function segmentMap(manifest) {
  return Object.fromEntries(manifest.segments.map((segment) => [segment.name, segment]));
}

async function installCursor(page) {
  await page.addStyleTag({
    content: `
      * { cursor: none !important; }
      #codexDemoCursor {
        position: fixed;
        left: 0;
        top: 0;
        width: 18px;
        height: 18px;
        border-radius: 999px;
        background: rgba(15, 119, 155, 0.9);
        box-shadow: 0 0 0 6px rgba(15, 119, 155, 0.14);
        pointer-events: none;
        z-index: 999999;
        transform: translate(-50%, -50%);
        transition: left 0.45s ease, top 0.45s ease, transform 0.15s ease, box-shadow 0.2s ease;
      }
      #codexDemoCursor.clicking {
        transform: translate(-50%, -50%) scale(0.86);
        box-shadow: 0 0 0 12px rgba(15, 119, 155, 0.08);
      }
    `,
  });

  await page.evaluate(() => {
    const cursor = document.createElement("div");
    cursor.id = "codexDemoCursor";
    cursor.style.left = "120px";
    cursor.style.top = "120px";
    document.body.appendChild(cursor);

    window.__codexDemoCursor = {
      move(x, y, duration = 450) {
        cursor.style.transitionDuration = `${duration}ms`;
        cursor.style.left = `${x}px`;
        cursor.style.top = `${y}px`;
      },
      click() {
        cursor.classList.add("clicking");
        setTimeout(() => cursor.classList.remove("clicking"), 160);
      },
    };
  });
}

async function moveCursor(page, x, y, duration = 450) {
  await page.evaluate(
    ({ xPos, yPos, moveDuration }) => window.__codexDemoCursor.move(xPos, yPos, moveDuration),
    { xPos: x, yPos: y, moveDuration: duration },
  );
  await page.mouse.move(x, y, { steps: 18 });
  await sleep(duration + 40);
}

async function clickSelector(page, selector, waitAfter = 700) {
  const locator = page.locator(selector);
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  if (!box) {
    throw new Error(`Unable to click ${selector}: no bounding box`);
  }

  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await moveCursor(page, x, y, 500);
  await page.evaluate(() => window.__codexDemoCursor.click());
  await page.mouse.down();
  await page.mouse.up();
  await locator.click({ force: true });
  await sleep(waitAfter);
}

async function waitUntil(startTime, secondsFromStart) {
  const elapsed = (Date.now() - startTime) / 1000;
  const remaining = secondsFromStart - elapsed;
  if (remaining > 0) {
    await sleep(remaining * 1000);
  }
}

async function main() {
  await fs.mkdir(rawDir, { recursive: true });
  const manifest = JSON.parse(await fs.readFile(manifestPath, "utf8"));
  const segments = segmentMap(manifest);

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport,
    recordVideo: { dir: rawDir, size: viewport },
    locale: "zh-CN",
    deviceScaleFactor: 1,
  });

  const page = await context.newPage();
  page.setDefaultTimeout(30000);

  await page.goto("http://127.0.0.1:4173", { waitUntil: "networkidle" });
  await installCursor(page);
  await sleep(500);

  const startedAt = Date.now();

  await waitUntil(startedAt, 1.7);
  await clickSelector(page, "#connectBtn", 400);
  await page.waitForFunction(() => document.getElementById("statusPill")?.textContent?.includes("在线"), null, { timeout: 20000 });

  await waitUntil(startedAt, segments.us_ai.start - 1.9);
  await clickSelector(page, '[data-preset="us-ai"]', 450);
  await waitUntil(startedAt, segments.us_ai.start - 0.9);
  await clickSelector(page, "#generateBtn", 400);
  await page.waitForFunction(() => document.getElementById("summaryText")?.textContent?.includes("美国"), null, { timeout: 15000 });

  await waitUntil(startedAt, segments.uk_finance.start - 1.9);
  await clickSelector(page, '[data-preset="uk-finance"]', 450);
  await waitUntil(startedAt, segments.uk_finance.start - 0.9);
  await clickSelector(page, "#generateBtn", 400);
  await page.waitForFunction(() => document.getElementById("summaryText")?.textContent?.includes("英国"), null, { timeout: 15000 });

  await waitUntil(startedAt, segments.hk_media.start - 1.9);
  await clickSelector(page, '[data-preset="hk-media"]', 450);
  await waitUntil(startedAt, segments.hk_media.start - 0.9);
  await clickSelector(page, "#generateBtn", 400);
  await page.waitForFunction(() => document.getElementById("summaryText")?.textContent?.includes("香港"), null, { timeout: 15000 });

  await waitUntil(startedAt, manifest.total_duration + 1.5);

  const video = page.video();
  await page.close();
  await context.close();
  await browser.close();

  const recordedPath = await video.path();
  const finalRawPath = path.join(workDir, "studybridge-raw.webm");
  await fs.copyFile(recordedPath, finalRawPath);

  console.log(finalRawPath);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
