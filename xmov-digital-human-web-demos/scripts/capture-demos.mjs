import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const demos = [
  { slug: "scenic-guide", action: ".spot:nth-of-type(2)" },
  { slug: "care-companion", action: ".item:nth-of-type(4)" },
  { slug: "science-lab", action: "#askWhy" },
  { slug: "shopping-host", action: ".product:nth-of-type(2)" },
  { slug: "front-desk", action: ".service:nth-of-type(1)" },
  { slug: "wellness-buddy", action: ".moods button:nth-of-type(1)" },
  { slug: "interview-coach", action: ".qa button:nth-of-type(1)" },
  { slug: "legal-guide", action: ".topic:nth-of-type(1)" },
  { slug: "museum-curator", action: ".work:nth-of-type(2)" },
];

const baseUrl = "http://127.0.0.1:4173/demos";
const outputDir = path.resolve(process.cwd(), "..", "output", "playwright", "demo-screens");
fs.mkdirSync(outputDir, { recursive: true });

const browser = await chromium.launch({ headless: true });

for (const demo of demos) {
  const page = await browser.newPage({ viewport: { width: 1600, height: 1040 }, deviceScaleFactor: 1 });
  page.on("console", (message) => {
    if (message.type() === "error") {
      console.error(`[${demo.slug}] console error: ${message.text()}`);
    }
  });

  try {
    await page.goto(`${baseUrl}/${demo.slug}.html`, { waitUntil: "networkidle" });
    await page.waitForTimeout(1200);

    const connect = page.locator("#connectBtn");
    if (await connect.count()) {
      await connect.click();
      await page.waitForFunction(() => {
        const status = document.querySelector("#statusPill")?.textContent || "";
        return /在线|直播/.test(status);
      }, { timeout: 20000 }).catch(() => page.waitForTimeout(8000));
    }

    if (demo.action) {
      const action = page.locator(demo.action).first();
      if (await action.count()) {
        await action.click();
        await page.waitForTimeout(1800);
      }
    }

    await page.screenshot({
      path: path.join(outputDir, `${demo.slug}.png`),
      fullPage: false,
    });
    console.log(`captured ${demo.slug}`);
  } finally {
    await page.close();
  }
}

await browser.close();
