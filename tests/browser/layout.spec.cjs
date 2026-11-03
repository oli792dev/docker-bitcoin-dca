const {test, expect} = require('playwright/test');
const {execFileSync} = require('node:child_process');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
const pages = JSON.parse(execFileSync(process.env.PYTHON || 'python3', ['-m', 'tests.browser.pages'], {cwd: root, encoding: 'utf8'}));
const analytics = {
  quote: 'EUR', configuration: {displayCurrency: 'EUR', liveTrading: false, withdrawalsEnabled: false},
  snapshot: {price: 60000}, summary: {boughtBtc: .01, buyCount: 1, withdrawnBtc: 0, netBtc: .01},
  summaryByCurrency: {EUR: {buyVolume: 500, tradeFees: 1}}, depositsByCurrency: {EUR: {amount: 600}},
  activities: [], pagination: {total: 0, pages: 1, page: 1},
};
test.beforeEach(async ({page}) => {
  let paused=false;
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'https://dca.test') throw new Error(`Unexpected external request: ${url.origin}`);
    const rendered=pages[url.pathname+url.search]||pages[url.pathname];
    if (rendered) return route.fulfill({contentType: 'text/html', body: rendered});
    if(url.pathname==='/api/settings/pause')paused=route.request().postDataJSON().paused;
    const data = url.pathname === '/api/controls' ? {paused,until:null} : url.pathname === '/api/analytics' ? analytics
      : url.pathname === '/api/market-price' ? {price: 60000, conversionRate: 1, conversionRates: {EUR: 1}}
      : url.pathname === '/api/schedule' ? {botStatusLabel: 'Fixture ready', dashboardRefreshSeconds: 3600, quote: 'EUR', quoteBalance: 600}
      : url.pathname === '/api/withdrawals' ? [] : {};
    return route.fulfill({contentType: 'application/json', body: JSON.stringify(data)});
  });
});
async function noPageOverflow(page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
}
async function rect(locator) { return locator.boundingBox(); }

test('dashboard controls, analysis spacing and modal scroll restoration', async ({page}) => {
  await page.goto('/');
  await expect(page.locator('#investedTotal')).toContainText('501');
  await expect(page.locator('#botStatusLabel')).toHaveText('Fixture ready');
  await noPageOverflow(page);
  const disclosures = page.locator('details.report-details,details.period-activities,details.dashboard-footnotes');
  expect(await disclosures.evaluateAll(items => items.every(item => !item.open))).toBe(true);
  for (const id of ['monthRange', 'customRange', 'openSettings']) {
    expect((await rect(page.locator(`#${id}`))).height).toBeGreaterThanOrEqual(44);
  }
  await page.emulateMedia({colorScheme: 'dark'});
  await expect(page.locator('.period-shortcuts')).toHaveCSS('background-color', 'rgb(28, 28, 30)');
  const selectedRange = page.locator('#customRange');
  const hoverRange = page.locator('#monthRange');
  await expect(selectedRange).toHaveCSS('background-color', 'rgb(86, 86, 90)');
  const selectedBackground = await selectedRange.evaluate(el => getComputedStyle(el).backgroundColor);
  await hoverRange.hover();
  await expect(hoverRange).toHaveCSS('background-color', 'rgb(58, 58, 60)');
  expect(await hoverRange.evaluate(el => getComputedStyle(el).backgroundColor)).not.toBe(selectedBackground);
  expect(await selectedRange.evaluate(el => getComputedStyle(el).backgroundColor)).toBe(selectedBackground);
  const heading = await rect(page.locator('.analysis-header'));
  const report = await rect(page.locator('#periodReport'));
  expect(report.y).toBeGreaterThanOrEqual(heading.y + heading.height);
  async function verticalGap(first, second) {
    const a = await rect(page.locator(first));
    const b = await rect(page.locator(second));
    return Math.round(b.y - a.y - a.height);
  }
  await expect.poll(() => verticalGap('.report-primary', '.report-details>summary')).toBe(8);
  await page.locator('.report-details>summary').click();
  await expect.poll(() => verticalGap('.report-details>summary', '.report-extra')).toBe(8);
  await expect.poll(() => verticalGap('.report-extra', '.period-activities>summary')).toBe(8);
  await page.locator('.period-activities>summary').click();
  await expect.poll(() => verticalGap('.period-activities>summary', '.activity-panel')).toBe(8);
  const button = page.locator('#openSettings');
  await button.evaluate(el => { el.textContent = 'A deliberately long translated settings button label that must wrap'; el.style.width = '160px'; });
  expect((await rect(button)).height).toBeGreaterThan(44);
  await page.locator('#editCustomRange').scrollIntoViewIfNeeded();
  const scrollBefore = await page.evaluate(() => scrollY);
  await page.locator('#editCustomRange').click();
  await expect(page.locator('#rangeDialog')).toBeVisible();
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.body).position)).toBe('fixed');
  await page.keyboard.press('Escape');
  await expect(page.locator('#rangeDialog')).not.toBeVisible();
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.body).position)).not.toBe('fixed');
  await expect.poll(() => page.evaluate(() => scrollY)).toBe(scrollBefore);
  const summary = page.locator('.dashboard-footnotes>summary');
  const normalColor = await summary.evaluate(el => getComputedStyle(el).color);
  await summary.hover();
  expect(await summary.evaluate(el => getComputedStyle(el).color)).toBe(normalColor);
  expect(await summary.evaluate(el => getComputedStyle(el).webkitTapHighlightColor)).toBe('rgba(0, 0, 0, 0)');
  await summary.click();
  await page.reload();
  expect(await disclosures.evaluateAll(items => items.every(item => !item.open))).toBe(true);
  await page.evaluate(() => window.scrollTo(0, 0));
  await expect(page.locator('#openSettings')).toBeVisible();
  await page.locator('#openSettings').click();
  await expect(page.locator('.settings-dialog')).toHaveCSS('background-color', 'rgb(0, 0, 0)');
  await expect(page.locator('.settings-dialog-header')).toHaveCSS('background-color', 'rgb(0, 0, 0)');
  await expect(page.frameLocator('#settingsFrame').locator('body')).toHaveCSS('background-color', 'rgb(0, 0, 0)');

});

test('settings tabs stay single line and fields scroll within the content', async ({page,isMobile}) => {
  await page.goto('/settings');
  await expect(page.locator('#settingsForm')).toBeVisible();
  await noPageOverflow(page);
  const tabs = page.getByRole('tab');
  for (const tab of await tabs.all()) {
    expect(await tab.evaluate(el => getComputedStyle(el).whiteSpace)).toBe('nowrap');
    expect((await rect(tab)).height).toBeGreaterThanOrEqual(44);
  }
  await page.emulateMedia({colorScheme: 'dark'});
  await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(0, 0, 0)');
  await expect(page.locator('.settings-footer')).toHaveCSS('background-color', 'rgb(0, 0, 0)');
  await expect(page.locator('.settings-tabs')).toHaveCSS('background-color', 'rgb(28, 28, 30)');
  // Pointer-capable projects test hover. Touch projects use taps and verify
  // selection because emulated hover is not a stable touch interaction.
  await page.mouse.move(0,0);
  const selectedTab = page.locator('#botConfigurationTab');
  const hoverTab = page.locator('#exchangeConnectionTab');
  await expect(selectedTab).toHaveCSS('background-color', 'rgb(86, 86, 90)');
  const selectedBackground = await selectedTab.evaluate(el => getComputedStyle(el).backgroundColor);
  if(isMobile){
    await hoverTab.tap();
    await expect(hoverTab).toHaveAttribute('aria-selected','true');
    await selectedTab.tap();
    await expect(selectedTab).toHaveAttribute('aria-selected','true');
  }else{
    await hoverTab.hover();
    await expect(hoverTab).toHaveCSS('background-color', 'rgb(58, 58, 60)');
    expect(await hoverTab.evaluate(el => getComputedStyle(el).backgroundColor)).not.toBe(selectedBackground);
    expect(await selectedTab.evaluate(el => getComputedStyle(el).backgroundColor)).toBe(selectedBackground);
  }
  await expect(page.locator('#pauseTransactions')).toBeDisabled();
  await page.locator('#live').check();
  await expect(page.locator('#pauseTransactions')).toBeEnabled();
  await page.locator('#pauseTransactions').check();
  await page.locator('#live').uncheck();
  await expect(page.locator('#pauseTransactions')).not.toBeChecked();
  await expect(page.locator('#pauseTransactions')).toBeDisabled();
  const time = page.locator('#deposit_time');
  const pair = await rect(page.locator('#depositDateFields'));
  const timeBox = await rect(time);
  expect(timeBox.x).toBeGreaterThanOrEqual(pair.x - 1);
  expect(timeBox.x + timeBox.width).toBeLessThanOrEqual(pair.x + pair.width + 1);
  const content = page.locator('#settingsContent');
  expect(await content.evaluate(el => ['auto', 'scroll'].includes(getComputedStyle(el).overflowY))).toBe(true);
  // A short window must scroll fields rather than grow the whole settings page.
  await page.setViewportSize({...page.viewportSize(), height: 550});
  await content.evaluate(el => { el.scrollTop = el.scrollHeight; });
  expect(await content.evaluate(el => el.scrollTop)).toBeGreaterThan(0);
  await page.locator('#exchangeConnectionTab').click();
  await expect(page.locator('#kraken_api_key')).toBeVisible();
  const key = page.locator('#kraken_api_key');
  expect(await key.locator('..').locator('label').evaluate(el => ['left', 'start'].includes(getComputedStyle(el).textAlign))).toBe(true);
  await page.locator('#dashboardOptionsTab').click();
  await expect(page.locator('#language')).toBeVisible();
  await page.locator('#dashboardOptionsTab').press('Home');
  await expect(page.locator('#botConfigurationTab')).toHaveAttribute('aria-selected', 'true');
});

test('login stays contained and submits the production form contract', async ({page}) => {
  await page.goto('/login');
  await noPageOverflow(page);
  const submit = page.getByRole('button', {name: 'Sign in'});
  expect((await rect(submit)).height).toBeGreaterThanOrEqual(44);
  await page.locator('#username').fill('fixture-user');
  await page.locator('#password').fill('fixture-password');
  const request = page.waitForRequest(r => r.method() === 'POST' && new URL(r.url()).pathname === '/login');
  await submit.click();
  expect((await request).postData()).toBe('username=fixture-user&password=fixture-password');
});

test('all dialog surfaces and action bars match the page background', async ({page}) => {
  for (const route of ['/', '/settings']) {
    await page.goto(route);
    for (const [colorScheme, background] of [['dark', 'rgb(0, 0, 0)'], ['light', 'rgb(245, 245, 247)']]) {
      await page.emulateMedia({colorScheme});
      await expect(page.locator('body')).toHaveCSS('background-color', background);
      for (const dialog of await page.locator('dialog').all()) {
        await dialog.evaluate(el => el.showModal());
        await expect(dialog).toHaveCSS('background-color', background);
        for (const actions of await dialog.locator('.confirmation-actions,.actions').all()) {
          await expect(actions).toHaveCSS('background-color', background);
        }
        await dialog.evaluate(el => el.close());
      }
    }
  }
});

test('operational controls, backup review and Activity filters remain usable', async ({page}) => {
  await page.route('**/settings*',route=>route.fulfill({contentType:'text/html',body:pages['/settings-live'+new URL(route.request().url()).search]}));
  await page.goto('/settings');
  await page.getByRole('tab', {name:'Bot Configuration',exact:true}).click();
  await expect(page.locator('#pauseTransactions')).toBeVisible();
  await expect(page.locator('#pauseTransactions')).toBeEnabled();
  await page.locator('#pauseTransactions').check();
  await page.locator('#live').uncheck();
  await expect(page.locator('#pauseTransactions')).toBeDisabled();
  await expect(page.locator('#pauseTransactions')).not.toBeChecked();
  await page.locator('#live').check();
  await expect(page.locator('#pauseTransactions')).toBeEnabled();
  await page.getByRole('tab', {name:'Backup',exact:true}).click();
  await expect(page.locator('#backupLoginPassword')).toBeVisible();
  await expect(page.locator('#backupPassword')).toBeVisible();
  await expect(page.getByRole('heading',{name:'Create encrypted backup',exact:true})).toBeVisible();
  await expect(page.locator('#backupStatus')).toHaveCount(0);
  await expect(page.locator('#restoreBackup')).toBeDisabled();
  let backupRequests=0;
  await page.route('**/api/settings/backup',route=>{backupRequests++;return route.fulfill({contentType:'application/json',body:JSON.stringify({filename:'example.dcabackup',archive:Buffer.from('encrypted fixture').toString('base64')})})});
  await page.locator('#backupLoginPassword').fill('same-dashboard-password');
  await page.locator('#backupPassword').fill('same-dashboard-password');
  await page.locator('#createBackup').click();
  await expect(page.locator('#backupPasswordError')).toContainText('must be different');
  expect(backupRequests).toBe(0);
  await page.locator('#backupPassword').fill('different-backup-password');
  const downloaded=page.waitForEvent('download');
  await page.locator('#createBackup').click();await downloaded;
  await expect(page.locator('#backupPasswordError')).toBeHidden();
  await expect(page.locator('#backupStatus')).toHaveCount(0);

  await expect(page.locator('#restoreFileHint')).toContainText('Activity only or the full configuration');
  const download=page.locator('#createBackup'),manual=page.locator('#settingsWithdraw');
  expect((await rect(download)).height).toBe(44);
  await expect(download).toHaveCSS('border-top-color','rgba(0, 0, 0, 0)');
  await expect(page.locator('#restoreBackup')).toHaveCSS('border-top-color','rgba(0, 0, 0, 0)');
  const backupGroups=page.locator('.backup-groups>.settings-group');
  const first=await rect(backupGroups.nth(0)),second=await rect(backupGroups.nth(1));
  if(page.viewportSize().width>=900)expect(Math.round(first.y)).toBe(Math.round(second.y));
  else expect(second.y-first.y-first.height).toBeGreaterThanOrEqual(24);
  await expect(page.locator('#chooseRestoreFile')).toHaveText('Choose file');
  await expect(page.locator('#restoreFile')).toBeHidden();
  await expect(page.locator('#restoreFileName')).toBeHidden();
  const fileChooser=page.waitForEvent('filechooser');
  await page.locator('#chooseRestoreFile').click();
  await (await fileChooser).setFiles({name:'example.dcabackup',mimeType:'application/octet-stream',buffer:Buffer.from('encrypted fixture')});
  await expect(page.locator('#restoreFileName')).toHaveText('example.dcabackup');
  await page.locator('#restoreBackup').click();
  await expect(page.locator('#backupReview')).toBeVisible();
  await expect(page.locator('#backupReview')).toContainText('login credentials');
  await page.locator('#cancelBackupRestore').click();
  await expect(page.locator('#backupReview')).not.toBeVisible();
  await noPageOverflow(page);
  await page.screenshot({path:test.info().outputPath('backup-settings.png')});
  await page.goto('/');
  await page.locator('#activityHeading').click();
  const response=page.waitForRequest(request=>request.url().includes('/api/analytics')&&request.url().includes('q=Kraken')&&new URL(request.url()).searchParams.has('tz'));
  await page.locator('#activitySearch').click();
  await page.locator('#activitySearch').pressSequentially('Kraken');
  await expect(page.locator('#activitySearch')).toHaveValue('Kraken');
  await response;
  await expect(page.locator('#activityType')).toHaveCount(0);
  await expect(page.locator('#activityStatusFilter')).toHaveCount(0);
  await expect(page.getByText('Why this next purchase?',{exact:true})).toBeVisible();
  await noPageOverflow(page);
  await page.evaluate(()=>window.scrollTo(0,0));
  await expect(page.locator('#openSettings')).toBeVisible();
  await page.locator('#openSettings').click();
  const frame=page.frameLocator('#settingsFrame');
  await frame.getByRole('tab',{name:'Bot Configuration',exact:true}).click();
  await frame.locator('#buy_amount').fill('0.001');
  await frame.locator('#pauseTransactions').check();
  await frame.locator('#save').click();
  await expect(frame.locator('#review')).toBeVisible();
  await expect(frame.locator('#reviewValues')).toContainText('Pause transactions');
  await frame.locator('#cancel').click();
  await expect(frame.locator('#pauseTransactions')).toBeChecked();
  await expect(frame.locator('#buy_amount')).toHaveValue('0.001');
  await expect(page.locator('#settingsDialog')).toBeVisible();
});

test('Activity dates are unboxed links and details use responsive columns', async ({page,isMobile})=>{
 await page.route('**/api/analytics?**',route=>route.fulfill({contentType:'application/json',body:JSON.stringify({...analytics,activities:[{activityId:'example',datetime:'2026-10-29T12:00:00Z',type:'Buy',shares:.001,price:81000,amount:81,fee:.2,currency:'EUR',status:'confirmed'}],pagination:{total:1,pages:1,page:1}})}));
 await page.route('**/api/activity/detail?**',route=>route.fulfill({contentType:'application/json',body:JSON.stringify({id:'example',exchange:'KRAKEN',row:{datetime:'2026-10-29T12:00:00Z',type:'Buy',shares:'.001',price:'81000',amount:'81',fee:'.2',currency:'EUR'}})}));
 await page.goto('/');await page.locator('#activityHeading').click();
 const date=page.locator('.activity-date-link');await expect(date).toBeVisible();
 await expect(date).toHaveCSS('border-top-width','0px');await expect(date).toHaveCSS('background-color','rgba(0, 0, 0, 0)');
 await date.click();await expect(page.locator('#activityDetail')).toBeVisible();
 await noPageOverflow(page);
 const fields=page.locator('.activity-detail-field');await expect(fields.first()).toBeVisible();
 const first=await rect(fields.nth(0)),second=await rect(fields.nth(1));
 if(isMobile)expect(second.y).toBeGreaterThan(first.y);else{await expect.poll(async()=>{const a=await rect(fields.nth(0)),b=await rect(fields.nth(1));return Math.abs(a.y-b.y)}).toBeLessThan(1);expect((await rect(page.locator('#activityDetail'))).width).toBeGreaterThan(700)}
 await expect(page.locator('#activityDetail')).toHaveCSS('opacity','1');
 await page.screenshot({path:test.info().outputPath('activity-details.png')});
});

test('purchase explanation uses compact responsive field columns',async({page,isMobile})=>{
 await page.goto('/');
 await page.locator('.purchase-explanation>summary').click();
 const fields=page.locator('#purchaseExplanation>.purchase-explanation-field');
 await expect(fields).toHaveCount(12);
 const a=await rect(fields.nth(0)),b=await rect(fields.nth(1));
 if(isMobile)expect(b.y).toBeGreaterThan(a.y);else expect(Math.abs(b.y-a.y)).toBeLessThan(1);
 await noPageOverflow(page);
});
