import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, "..");
const outputDir = path.resolve(projectRoot, "output", "video");

const ffmpegPath = process.env.FFMPEG_PATH || "ffmpeg";
const videoPath = path.join(outputDir, "studybridge-demo-01-real-video.mp4");
const audioPath = path.join(outputDir, "studybridge-demo-01-real-audio.webm");
const finalPath = path.join(outputDir, "studybridge-demo-01-real.mp4");

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function ensureOutputDir() {
  await fs.mkdir(outputDir, { recursive: true });
}

async function waitForSpeechToStart(page, timeout = 12000) {
  try {
    await page.waitForFunction(() => {
      const audioElement =
        window.__studyAdvisorApp?.avatar?.renderScheduler?.audioRenderer?.mseAudioPlayer?.audioElement;
      return !!audioElement && !audioElement.paused;
    }, { timeout });
  } catch {
    // Some flows start and finish quickly enough that the recorder still catches the full result.
  }
}

async function waitForSpeechToFinish(page, timeout = 50000) {
  await page.waitForFunction(() => {
    const audioElement =
      window.__studyAdvisorApp?.avatar?.renderScheduler?.audioRenderer?.mseAudioPlayer?.audioElement;
    return !audioElement || audioElement.paused;
  }, { timeout });
}

function startVideoCapture() {
  const args = [
    "-y",
    "-hide_banner",
    "-f",
    "gdigrab",
    "-framerate",
    "30",
    "-draw_mouse",
    "0",
    "-offset_x",
    "-1536",
    "-offset_y",
    "0",
    "-video_size",
    "1536x960",
    "-i",
    "desktop",
    "-c:v",
    "libx264",
    "-preset",
    "veryfast",
    "-pix_fmt",
    "yuv420p",
    "-crf",
    "18",
    videoPath,
  ];

  const proc = spawn(ffmpegPath, args, {
    stdio: ["pipe", "pipe", "pipe"],
  });

  proc.stdout.on("data", () => {});
  proc.stderr.on("data", () => {});

  return proc;
}

async function stopVideoCapture(proc) {
  await new Promise((resolve, reject) => {
    proc.once("error", reject);
    proc.once("close", (code) => {
      if (code === 0) {
        resolve();
        return;
      }
      reject(new Error(`ffmpeg exited with code ${code}`));
    });
    proc.stdin.write("q");
    proc.stdin.end();
  });
}

async function startAudioRecorder(page) {
  await page.evaluate(async () => {
    const waitForAudioElement = async () => {
      const deadline = Date.now() + 15000;
      while (Date.now() < deadline) {
        const app = window.__studyAdvisorApp;
        const audioElement =
          app?.avatar?.renderScheduler?.audioRenderer?.mseAudioPlayer?.audioElement;
        if (audioElement) {
          return audioElement;
        }
        await new Promise((resolve) => setTimeout(resolve, 200));
      }
      throw new Error("MSE audio element not found");
    };

    const audioElement = await waitForAudioElement();
    const audioContext = new AudioContext({ sampleRate: 48000 });
    await audioContext.resume();
    const source = audioContext.createMediaElementSource(audioElement);
    const destination = audioContext.createMediaStreamDestination();
    source.connect(destination);

    const chunks = [];
    const recorder = new MediaRecorder(destination.stream, {
      mimeType: "audio/webm;codecs=opus",
    });

    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size) {
        chunks.push(event.data);
      }
    };

    recorder.start(250);
    window.__studyBridgeRecorder = {
      audioContext,
      chunks,
      recorder,
    };
  });
}

async function stopAudioRecorder(page) {
  const downloadPromise = page.waitForEvent("download");
  await page.evaluate(async () => {
    const session = window.__studyBridgeRecorder;
    if (!session) {
      throw new Error("Audio recorder session not found");
    }

    await new Promise((resolve) => {
      session.recorder.onstop = resolve;
      session.recorder.stop();
    });

    const blob = new Blob(session.chunks, { type: "audio/webm" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "studybridge-audio.webm";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    await session.audioContext.close();
  });

  const download = await downloadPromise;
  await download.saveAs(audioPath);
}

async function renderFinalVideo() {
  const args = [
    "-y",
    "-hide_banner",
    "-i",
    videoPath,
    "-i",
    audioPath,
    "-c:v",
    "copy",
    "-c:a",
    "aac",
    "-b:a",
    "192k",
    "-shortest",
    finalPath,
  ];

  await new Promise((resolve, reject) => {
    const proc = spawn(ffmpegPath, args, { stdio: "inherit" });
    proc.once("error", reject);
    proc.once("close", (code) => {
      if (code === 0) {
        resolve();
        return;
      }
      reject(new Error(`mux ffmpeg exited with code ${code}`));
    });
  });
}

async function runScenario(page, presetKey, waitAfter = 2500) {
  await page.locator(`[data-preset="${presetKey}"]`).click();
  await sleep(700);
  await page.locator("#generateBtn").click();
  await waitForSpeechToStart(page, 15000);
  await waitForSpeechToFinish(page, 50000);
  await sleep(waitAfter);
}

async function main() {
  await ensureOutputDir();

  const browser = await chromium.launch({
    headless: false,
    args: [
      "--window-position=-1536,0",
      "--window-size=1536,960",
      "--kiosk",
      "--disable-backgrounding-occluded-windows",
      "--disable-renderer-backgrounding",
      "--disable-background-timer-throttling",
      "--disable-features=CalculateNativeWinOcclusion",
    ],
  });

  const context = await browser.newContext({
    acceptDownloads: true,
    viewport: { width: 1536, height: 960 },
  });
  const page = await context.newPage();

  try {
    await page.goto("http://127.0.0.1:4173", { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1800);
    await page.locator("#connectBtn").click();
    await page.waitForFunction(() => window.__studyAdvisorApp?.connected === true, {
      timeout: 30000,
    });
    await waitForSpeechToStart(page, 15000);
    await waitForSpeechToFinish(page, 60000);
    await page.waitForTimeout(1000);

    const ffmpegProc = startVideoCapture();
    await page.waitForTimeout(1200);
    await startAudioRecorder(page);
    await page.waitForTimeout(1000);

    await runScenario(page, "us-ai");
    await runScenario(page, "uk-finance");
    await runScenario(page, "sg-analytics", 1800);

    await stopAudioRecorder(page);
    await stopVideoCapture(ffmpegProc);
    await renderFinalVideo();
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
