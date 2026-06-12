// Throwaway verification: the FastAPI server (:8000) now serves the SPA shell
// on '/', '/projects/{slug}' and run detail (via the /run 308 redirect), while
// legacy chart pages keep working. Saves screenshots next to this script.
import { chromium } from 'playwright'

const BASE = 'http://localhost:8000'
const OUT = new URL('.', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')

const browser = await chromium.launch({ channel: 'msedge', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

const failures = []
page.on('pageerror', (err) => failures.push(`pageerror: ${err.message}`))
page.on('console', (msg) => {
  if (msg.type() === 'error') failures.push(`console.error: ${msg.text()}`)
})

// 1. SPA root served by FastAPI
await page.goto(`${BASE}/`, { waitUntil: 'networkidle' })
const boot = await page.evaluate(() => ({
  root: window.__QYM_ROOT_PATH__,
  boot: window.__QYM_BOOT__,
  rendered: document.querySelector('#root')?.children.length > 0,
}))
console.log('root page boot:', JSON.stringify(boot))
await page.screenshot({ path: `${OUT}spa-serve-root.png`, fullPage: false })

// 2. /run/{id} 308 → canonical SPA run detail
const runsResp = await page.request.get(`${BASE}/v1/runs?project_slug=support-copilot&limit=1`)
const runId = (await runsResp.json()).runs[0].id
await page.goto(`${BASE}/run/${runId}`, { waitUntil: 'networkidle' })
console.log('after /run redirect, url:', page.url())
await page.screenshot({ path: `${OUT}spa-serve-run-detail.png`, fullPage: false })

// 3. Legacy charts page still loads its /static assets
await page.goto(`${BASE}/projects/support-copilot/charts`, { waitUntil: 'networkidle' })
console.log('charts title:', await page.title())
await page.screenshot({ path: `${OUT}spa-serve-legacy-charts.png`, fullPage: false })

console.log('js errors:', failures.length ? failures : 'none')
await browser.close()
if (!boot.rendered) {
  console.error('FAIL: SPA #root did not render')
  process.exit(1)
}
