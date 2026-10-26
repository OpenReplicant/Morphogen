// The browser half of test_ui.py: headless Chromium signs in to Morphogen's UI as a person, reads the plan
// waiting for review and the claims it cites, approves it, then opens the loop and the systems view; before that,
// the overview it opens on (the slots, their providers, one slot's panel). Prints one JSON line of what it saw.
// Env: UI (the page), NAME, PASSWORD, PLAN (the plan's label); SHOT, a file for a screenshot of the review lane.
// With STEP=plans it only signs in and reads the plan's row in the loop (who decided it, its run, its verdict),
// then opens the verdict.
const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  try {
    await page.goto(process.env.UI);
    await page.getByLabel('Name').fill(process.env.NAME);
    await page.getByLabel('Password').fill(process.env.PASSWORD);
    await page.getByRole('button', { name: 'Sign in' }).click();
    if (process.env.STEP === 'plans') {
      await page.locator('[data-test=agent]').waitFor({ timeout: 30000 });
      await page.locator('nav').getByRole('button', { name: 'Loop' }).click();
      const row = page.locator('tr[data-plan]', { hasText: process.env.PLAN });
      await row.locator('[data-test=verdict].click').waitFor({ timeout: 30000 });
      if (process.env.SHOT) await page.screenshot({ path: process.env.SHOT, fullPage: true });
      const cell = async t => row.locator(`[data-test=${t}]`).innerText();
      const [decided, run, verdict] = [await cell('decided'), await cell('run'), await cell('verdict')];
      await row.locator('[data-test=verdict]').click();
      await page.waitForFunction(() => document.querySelector('aside.detail pre') && document.querySelector('aside.detail pre').textContent.length > 2,
                                 null, { timeout: 30000 });
      const detail = await page.locator('aside.detail pre').textContent();
      if (errors.length) throw new Error('page errors: ' + errors.join(' | '));
      console.log(JSON.stringify({ decided, run, verdict, detail: JSON.parse(detail) }));
      return;
    }
    // The overview first: every slot from the record, with its providers; a slot opens with where its default is written.
    await page.locator('[data-test=overview] [data-slot=gap-finder]').waitFor({ timeout: 30000 });
    const slots = await page.locator('[data-test=overview] [data-slot]').count();
    const gapFinder = await page.locator('[data-slot=gap-finder] .chip.def').allInnerTexts();
    const tiles = {};
    for (const t of ['review', 'questions', 'drift', 'systems', 'slots', 'vocabularies'])
      tiles[t] = (await page.locator(`[data-test=tile-${t}] strong`).innerText()).trim();
    await page.locator('[data-slot=runtime]').click();
    await page.locator('[data-test=where]').waitFor({ timeout: 30000 });
    const runtime = { where: await page.locator('[data-test=where]').innerText(),
                      providers: await page.locator('[data-test=slot-panel] [data-provider]').evaluateAll(es => es.map(e => e.dataset.provider)),
                      defaults: await page.locator('[data-test=slot-panel] [data-provider]').evaluateAll(es =>
                        es.filter(e => e.querySelector('.pill.on').offsetParent !== null).map(e => e.dataset.provider)) };
    await page.locator('[data-test=slot-panel]').getByRole('button', { name: 'Close' }).click();
    await page.locator('nav').getByRole('button', { name: 'Review' }).click();
    const card = page.locator('article.card', { hasText: process.env.PLAN });
    await card.waitFor({ timeout: 30000 });
    await card.locator('tr[data-claim]').first().waitFor();
    if (process.env.SHOT) await page.screenshot({ path: process.env.SHOT, fullPage: true });
    const agent = await page.locator('[data-test=agent]').getAttribute('title');
    const prediction = await card.locator('[data-test=prediction]').innerText();
    const cited = await card.locator('tr[data-claim]').evaluateAll(rows =>
      rows.map(r => [r.dataset.claim, r.querySelector('td.num').innerText]));
    await card.getByRole('button', { name: 'Approve' }).click();
    await page.getByText('Nothing is waiting for your review.').waitFor({ timeout: 30000 });
    const after = await page.locator('article.card').count();
    await page.locator('nav').getByRole('button', { name: 'Loop' }).click();
    await page.locator('section[aria-label=Loop] tbody tr').first().waitFor({ timeout: 30000 });
    const loop = await page.locator('section[aria-label=Loop] tbody tr').allInnerTexts();
    await page.locator('nav').getByRole('button', { name: 'Systems' }).click();
    await page.waitForFunction(() => Number(document.getElementById('cy').dataset.nodes) > 0, null, { timeout: 30000 });
    const nodes = await page.locator('#cy').getAttribute('data-nodes');
    if (errors.length) throw new Error('page errors: ' + errors.join(' | '));
    console.log(JSON.stringify({ agent, prediction, cited, after, loop, nodes, slots, gapFinder, tiles, runtime }));
  } catch (e) {
    await page.screenshot({ path: (process.env.TMPDIR || '/tmp') + '/kk_ui_test.png' }).catch(() => {});
    console.error(String(e), errors.join(' | '));
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();
