/* Throwaway browser verification for the run detail page.
 * Run: node scripts/run-detail-verify.mjs   (dev server on :5182, backend on :8000)
 */
/* global console, process */
import { chromium } from '@playwright/test'

const BASE = 'http://localhost:5182'
const OUT = 'scripts'
const results = []

function check(name, ok, extra = '') {
  results.push({ name, ok })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? ` — ${extra}` : ''}`)
}

const browser = await chromium.launch({ channel: 'msedge', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })

try {
  // ── APPROVED run ──
  await page.goto(`${BASE}/projects/support-copilot/runs/f42571bf-99ba-4224-b5b3-33c061e197ac`, {
    waitUntil: 'networkidle',
  })
  await page.waitForSelector('h1')
  check('approved: h1 not a UUID', !/^[0-9a-f-]{36}$/i.test(await page.locator('h1').innerText()))
  check('approved: green banner', (await page.getByText(/approved by/i).count()) > 0)
  check('approved: verdict cards', (await page.getByText(/pass · /i).count()) >= 3)
  check('approved: trace one-liner', (await page.getByText(/no trace data/i).count()) === 1)
  check(
    'approved: compare enabled state present',
    (await page.getByRole('button', { name: 'Compare vs previous' }).count()) === 1,
  )
  await page.screenshot({ path: `${OUT}/run-detail-approved.png`, fullPage: true })

  // ── REJECTED run ──
  await page.goto(`${BASE}/projects/support-copilot/runs/0ea0b594-de57-42f6-9c89-010b681baa6f`, {
    waitUntil: 'networkidle',
  })
  await page.waitForSelector('h1')
  check('rejected: banner headline', (await page.getByText(/rejected by dev user on/i).count()) === 1)
  check(
    'rejected: banner comment',
    (await page.getByText('Pass rate too low on hard tickets, investigate retrieval').count()) === 1,
  )
  check('rejected: resubmit visible', (await page.getByRole('button', { name: 'Resubmit' }).count()) === 1)
  const failuresBtn = page.getByRole('button', { name: /^Failures \(/ })
  check(
    'rejected: failures segment default',
    (await failuresBtn.getAttribute('aria-pressed')) === 'true',
    await failuresBtn.innerText(),
  )
  await page.screenshot({ path: `${OUT}/run-detail-rejected.png`, fullPage: true })

  // ── Item expand on the rejected run ──
  await page.getByRole('button', { name: 'Expand item' }).first().click()
  await page.waitForSelector('text=Expected')
  // 'Input' appears twice once expanded: the table column header + the panel label.
  check('expanded: input panel', (await page.getByText('Input', { exact: true }).count()) === 2)
  check('expanded: output+expected', (await page.getByText('Expected', { exact: true }).count()) === 1)
  check('expanded: root cause block', (await page.getByText(/pending review/i).count()) >= 1)
  await page.screenshot({ path: `${OUT}/run-detail-item-expanded.png`, fullPage: true })

  // ── FAILED run (text2sql) ──
  await page.goto(`${BASE}/projects/text2sql/runs/55d7867b-8d68-4203-8da7-5a9e2e496904`, {
    waitUntil: 'networkidle',
  })
  await page.waitForSelector('h1')
  const failedH1 = await page.locator('h1').innerText()
  check('failed: name not a UUID', !/^[0-9a-f-]{36}$/i.test(failedH1), failedH1)
  check(
    'failed: failure banner',
    (await page.getByText(/failed after 3 of 10 items — CUDA out of memory/i).count()) === 1,
  )
  check(
    'failed: compare disabled',
    (await page.getByRole('button', { name: 'Compare vs previous' }).isDisabled()),
  )
  await page.screenshot({ path: `${OUT}/run-detail-failed.png`, fullPage: true })
} catch (error) {
  check('script completed', false, String(error))
} finally {
  await browser.close()
}

const failed = results.filter((r) => !r.ok)
console.log(`\n${results.length - failed.length}/${results.length} checks passed`)
process.exit(failed.length > 0 ? 1 : 0)
