import { expect, test } from '@playwright/test'

// Placeholder until the SPA is actually mounted by the backend.
test.skip('SPA shell loads from the FastAPI server', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveTitle(/qym/i)
})
