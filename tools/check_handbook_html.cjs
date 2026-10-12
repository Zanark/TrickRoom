const path = require("node:path");
const { pathToFileURL } = require("node:url");
const fs = require("node:fs");
const puppeteer = require(path.resolve("docs", "book", "node_modules", "puppeteer"));

(async () => {
  const browser = await puppeteer.launch({
    executablePath: "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    headless: true,
  });
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(String(error)));
    await page.setViewport({ width: 1280, height: 900 });
    await page.goto(pathToFileURL(path.resolve("docs", "book", "index.html")).href, {
      waitUntil: "load", timeout: 30000,
    });
    const result = await page.evaluate(async () => {
      await Promise.all([...document.images].map(image => image.decode()));
      return {
        headingCount: document.querySelectorAll("h2").length,
        images: document.images.length,
        decodedImages: [...document.images].every(image => image.naturalWidth > 0),
        externalImages: [...document.images].filter(image => !image.src.startsWith("data:")).length,
        contents: document.querySelector("details summary")?.textContent,
        horizontalOverflow: document.documentElement.scrollWidth > innerWidth,
      };
    });
    if (errors.length || result.headingCount !== 35 || result.images < 8 || !result.decodedImages ||
        result.externalImages || result.horizontalOverflow) {
      throw new Error(JSON.stringify({ errors, ...result }));
    }
    fs.mkdirSync(path.resolve(".local", "handbook-review"), { recursive: true });
    await page.screenshot({ path: path.resolve(".local", "handbook-review", "html-desktop.png") });
    fs.writeFileSync(path.resolve(".local", "handbook-review", "html-report.json"),
      JSON.stringify({ ...result, errors, passed: true }, null, 2));
    console.log(JSON.stringify(result, null, 2));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
