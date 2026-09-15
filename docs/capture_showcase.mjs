// Run from the repository root after: npm install --no-save playwright
import { chromium } from 'playwright';
import { fileURLToPath } from 'node:url';
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.goto(new URL('./output-showcase.html', import.meta.url).href);
await page.evaluate(() => document.fonts.ready);
await page.screenshot({ path: fileURLToPath(new URL('./output-showcase.png', import.meta.url)), fullPage: true });
await browser.close();
