/* Throwaway smoke test for the app shell + projects landing.
 * Run: node scripts/shell-smoke.mjs   (dev server on :5174, backend on :8000)
 */
/* global console, process, localStorage */
import { chromium } from '@playwright/test'

const BASE = 'http://localhost:5174'
const results = []

function check(name, ok, extra = '') {
  results.push({ name, ok, extra })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? ` — ${extra}` : ''}`)
}

const browser = await chromium.launch({ channel: 'msedge', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

try {
  // ── Home (global context) ──
  await page.goto(`${BASE}/`, { waitUntil: 'networkidle' })
  await page.waitForSelector('text=Customer Support Copilot', { timeout: 10_000 })

  check('brand text "qym" visible', await page.getByText('qym', { exact: true }).first().isVisible())
  for (const item of ['Projects', 'Docs', 'Admin']) {
    check(
      `global sidebar item: ${item}`,
      (await page.locator('aside nav').getByText(item, { exact: true }).count()) > 0,
    )
  }
  check('user chip shows Dev User', (await page.getByText('Dev User').count()) > 0)
  check(
    'project cards rendered',
    (await page.locator('a[href^="/projects/"]').count()) >= 3,
    `${await page.locator('a[href^="/projects/"]').count()} links`,
  )
  check('new project button', await page.getByRole('button', { name: 'New project' }).isVisible())

  // search filter
  await page.getByRole('searchbox').fill('sql')
  await page.waitForTimeout(150)
  check(
    'search filters cards',
    (await page.getByText('Text2SQL Bench').count()) > 0 &&
      (await page.getByText('Customer Support Copilot').count()) === 0,
  )
  await page.getByRole('searchbox').fill('')

  await page.screenshot({ path: 'scripts/shell-home.png', fullPage: false })

  // ── Click into a project (project context) ──
  await page.getByText('Customer Support Copilot').first().click()
  await page.waitForURL('**/projects/support-copilot', { timeout: 10_000 })
  await page.waitForSelector('text=Runs', { timeout: 10_000 })

  for (const item of ['Runs', 'Analysis', 'Review', 'Datasets', 'Settings', 'All projects']) {
    check(
      `project sidebar item: ${item}`,
      (await page.locator('aside').getByText(item, { exact: true }).count()) > 0,
    )
  }
  check(
    'project switcher shows project name',
    (await page.locator('aside').getByText('Customer Support Copilot').count()) > 0,
  )
  check(
    'breadcrumb shows Project / Section',
    (await page.locator('header').getByText('Customer Support Copilot').count()) > 0 &&
      (await page.locator('header').getByText('Runs').count()) > 0,
  )
  // exactly one active nav item
  const activeCount = await page.locator('aside [aria-current="page"]').count()
  check('exactly one active sidebar item', activeCount === 1, `${activeCount} active`)

  await page.screenshot({ path: 'scripts/shell-project.png', fullPage: false })

  // ── Navigate to a section: active state moves, stays single ──
  await page.locator('aside nav').getByText('Datasets', { exact: true }).click()
  await page.waitForURL('**/projects/support-copilot/datasets')
  const activeAfter = await page.locator('aside [aria-current="page"]').count()
  check('one active item after section change', activeAfter === 1, `${activeAfter} active`)

  // ── Collapse persists ──
  await page.getByRole('button', { name: 'Collapse sidebar' }).click()
  await page.waitForTimeout(200)
  check(
    'collapse persisted to localStorage',
    (await page.evaluate(() => localStorage.getItem('qym.sidebar.collapsed'))) === '1',
  )
  await page.getByRole('button', { name: 'Expand sidebar' }).click()

  // ── Create dialog opens ──
  await page.locator('aside nav').getByText('All projects', { exact: true }).click()
  await page.waitForURL(`${BASE}/`)
  await page.getByRole('button', { name: 'New project' }).click()
  await page.waitForSelector('role=dialog')
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Name', { exact: true }).fill('Smoke Probe')
  const slugValue = await dialog.getByLabel('Slug', { exact: true }).inputValue()
  check('slug auto-derived from name', slugValue === 'smoke-probe', slugValue)
  await page.keyboard.press('Escape')
} catch (err) {
  check('smoke run completed', false, String(err))
} finally {
  await browser.close()
}

const failed = results.filter((r) => !r.ok)
console.log(`\n${results.length - failed.length}/${results.length} checks passed`)
process.exit(failed.length === 0 ? 0 : 1)
