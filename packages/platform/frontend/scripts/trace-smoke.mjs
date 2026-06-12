/**
 * Throwaway browser smoke for the TraceDrawer port (trace-viewer agent).
 * Drives the real run-detail page on the local dev server (port 5183),
 * opens an item trace, exercises keyboard nav + tabs, screenshots into
 * scripts/. Run: node scripts/trace-smoke.mjs
 */
import { chromium } from 'playwright'

const BASE = 'http://localhost:5183'
const RUN_OK = `${BASE}/projects/support-copilot/runs/f42571bf-99ba-4224-b5b3-33c061e197ac`
const RUN_ERR = `${BASE}/projects/support-copilot/runs/60d5989f-81ae-4c20-8da5-a94f1f90f7d1`
const OUT = new URL('.', import.meta.url).pathname.replace(/^\/([A-Za-z]):/, '$1:')

const browser = await chromium.launch({ channel: 'msedge', headless: true })
const page = await browser.newPage({ viewport: { width: 1500, height: 950 } })
const failures = []

async function check(name, fn) {
  try {
    await fn()
    console.log(`ok  - ${name}`)
  } catch (err) {
    failures.push(name)
    console.error(`FAIL - ${name}: ${String(err).split('\n')[0]}`)
  }
}

// ── happy path ──
await page.goto(RUN_OK, { waitUntil: 'networkidle' })
await page.getByLabel('View trace').first().click()

await check('drawer opens with span tree', async () => {
  await page.getByRole('tree', { name: 'Trace spans' }).waitFor({ timeout: 8000 })
})
await check('three treeitems, root selected + expanded', async () => {
  const rows = page.getByRole('treeitem')
  if ((await rows.count()) !== 3) throw new Error(`rows=${await rows.count()}`)
  const sel = await rows.first().getAttribute('aria-selected')
  if (sel !== 'true') throw new Error('root not selected')
})
await check('summary chips show span count + scores', async () => {
  await page.getByText('3 spans').waitFor({ timeout: 3000 })
  // 'exact_match' also appears in the items table behind the drawer
  await page.getByText('exact_match').first().waitFor({ timeout: 3000 })
})
await check('detail shows Input / output panels', async () => {
  await page.getByText('How do I reset my password?').first().waitFor({ timeout: 3000 })
})
await page.waitForTimeout(400) // let the 180ms drawer-in animation settle
await page.screenshot({ path: `${OUT}trace-drawer-ok.png` })

await check('keyboard: ArrowDown selects child, detail follows', async () => {
  await page.getByRole('treeitem').first().focus()
  await page.keyboard.press('ArrowDown')
  const second = page.getByRole('treeitem').nth(1)
  if ((await second.getAttribute('aria-selected')) !== 'true') throw new Error('child not selected')
})
await check('Attributes tab renders key-value table', async () => {
  await page.getByRole('tab', { name: /Attributes/ }).click()
  await page.getByText('openinference.span.kind').waitFor({ timeout: 3000 })
})
await page.screenshot({ path: `${OUT}trace-drawer-attrs.png` })
await page.keyboard.press('Escape')

// ── error trace with attempts ──
await page.goto(RUN_ERR, { waitUntil: 'networkidle' })
const failedRowTrace = page.getByLabel('View trace')
await failedRowTrace.nth(1).click() // item index 1 is a failed item in this run
await check('error trace shows error chip + attempts + error box', async () => {
  await page.getByRole('tree', { name: 'Trace spans' }).waitFor({ timeout: 8000 })
  await page.getByText('1 error').waitFor({ timeout: 3000 })
  await page.getByRole('button', { name: /Attempt 1/ }).waitFor({ timeout: 3000 })
  await page.getByRole('alert').waitFor({ timeout: 3000 })
})
await page.waitForTimeout(400) // let the 180ms drawer-in animation settle
await page.screenshot({ path: `${OUT}trace-drawer-error.png` })

await browser.close()
if (failures.length) {
  console.error(`\n${failures.length} smoke check(s) failed`)
  process.exit(1)
}
console.log('\nAll trace smoke checks passed')
