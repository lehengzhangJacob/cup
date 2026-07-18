import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import url from "node:url";

const __dirname = path.dirname(url.fileURLToPath(import.meta.url));
const publicDir = path.join(__dirname, "public");
const envPath = path.join(__dirname, ".env");
const port = Number(process.env.PORT || 4173);
const recordingDir = path.join(__dirname, "output", "video-work");

function parseEnvFile(filePath) {
  if (!fs.existsSync(filePath)) {
    return {};
  }

  const content = fs.readFileSync(filePath, "utf8");
  const result = {};

  for (const rawLine of content.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) {
      continue;
    }

    const equalIndex = line.indexOf("=");
    if (equalIndex === -1) {
      continue;
    }

    const key = line.slice(0, equalIndex).trim();
    const value = line.slice(equalIndex + 1).trim();
    result[key] = value;
  }

  return result;
}

const env = {
  ...parseEnvFile(envPath),
  ...process.env,
};

function json(data, statusCode = 200) {
  return new Response(JSON.stringify(data), {
    status: statusCode,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}

function text(data, statusCode = 200, contentType = "text/plain; charset=utf-8") {
  return new Response(data, {
    status: statusCode,
    headers: {
      "Content-Type": contentType,
      "Cache-Control": "no-store",
    },
  });
}

function fileResponse(filePath) {
  if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
    return text("Not Found", 404);
  }

  const ext = path.extname(filePath).toLowerCase();
  const contentTypes = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
  };

  return new Response(fs.readFileSync(filePath), {
    status: 200,
    headers: {
      "Content-Type": contentTypes[ext] || "application/octet-stream",
      "Cache-Control": "no-store",
    },
  });
}

function buildClientConfig() {
  return {
    appId: env.XMOV_APP_ID || "",
    appSecret: env.XMOV_APP_SECRET || "",
    gatewayServer: env.XMOV_SESSION_GATEWAY_URL || "",
    authHeader: env.XMOV_AUTH_HEADER || "",
  };
}

const server = http.createServer(async (req, res) => {
  try {
    const reqUrl = new URL(req.url || "/", `http://${req.headers.host}`);
    let response;

    if (reqUrl.pathname === "/healthz") {
      response = json({ ok: true, port });
    } else if (reqUrl.pathname === "/api/recording-audio" && req.method === "POST") {
      fs.mkdirSync(recordingDir, { recursive: true });
      const chunks = [];
      for await (const chunk of req) {
        chunks.push(chunk);
      }

      const filePath = path.join(recordingDir, "studybridge-page-audio.webm");
      fs.writeFileSync(filePath, Buffer.concat(chunks));
      response = json({ ok: true, filePath });
    } else if (reqUrl.pathname === "/api/config") {
      response = json(buildClientConfig());
    } else if (reqUrl.pathname === "/config.js") {
      response = text(
        `window.__XMOV_CONFIG__ = ${JSON.stringify(buildClientConfig(), null, 2)};`,
        200,
        "application/javascript; charset=utf-8",
      );
    } else {
      const pathname = reqUrl.pathname === "/" ? "/index.html" : reqUrl.pathname;
      const safePath = path.normalize(pathname).replace(/^(\.\.[/\\])+/, "");
      response = fileResponse(path.join(publicDir, safePath));
    }

    res.writeHead(response.status, Object.fromEntries(response.headers.entries()));
    const body = Buffer.from(await response.arrayBuffer());
    res.end(body);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    res.writeHead(500, { "Content-Type": "text/plain; charset=utf-8" });
    res.end(`Server error: ${message}`);
  }
});

server.listen(port, "127.0.0.1", () => {
  console.log(`XMOV web check server running at http://127.0.0.1:${port}`);
});
