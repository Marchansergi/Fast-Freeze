// Renderiza el vídeo promocional: cada fotograma se dibuja con render(t) y se envía a ffmpeg.
// Uso: node render.mjs video <salida.mp4> [fps]   |   node render.mjs stills <carpeta> t1 t2 ...
import { createRequire } from "node:module";
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const { chromium } = createRequire(import.meta.url)("playwright"); // NODE_PATH con Playwright global
const here = path.dirname(fileURLToPath(import.meta.url));
const [mode, out, ...rest] = process.argv.slice(2);
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
page.on("pageerror", e => { console.error("Error en la página:", e.message); process.exit(1); });
await page.goto(pathToFileURL(path.join(here, "index.html")).href);
await page.evaluate(() => document.fonts.ready);
await page.waitForTimeout(300);

if (mode === "stills") {
  for (const t of rest) {
    await page.evaluate(x => window.render(x), Number(t));
    await page.screenshot({ path: path.join(out, `f_${String(t).padStart(5, "0")}.png`) });
  }
} else {
  const fps = Number(rest[0] || 60);
  const duration = await page.evaluate(() => window.DURATION);
  const frames = Math.round(duration * fps);
  const ff = spawn("ffmpeg", ["-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", String(fps), "-c:v", "mjpeg", "-i", "-",
    "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out], { stdio: ["pipe", "inherit", "inherit"] });
  const t0 = Date.now();
  for (let i = 0; i < frames; i++) {
    await page.evaluate(x => window.render(x), i / fps);
    const buf = await page.screenshot({ type: "jpeg", quality: 95 });
    if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once("drain", r));
    if (i % 120 === 0) console.log(`fotograma ${i}/${frames} (${((Date.now() - t0) / 1000).toFixed(0)} s)`);
  }
  ff.stdin.end();
  await new Promise((r, j) => ff.on("close", c => c === 0 ? r() : j(new Error("ffmpeg " + c))));
}
await browser.close();
