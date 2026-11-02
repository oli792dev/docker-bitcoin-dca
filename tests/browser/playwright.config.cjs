const {defineConfig} = require('playwright/test');
module.exports = defineConfig({
  testDir: __dirname,
  testMatch: '*.spec.cjs',
  fullyParallel: true,
  timeout: 30000,
  use: {headless: true, baseURL: 'https://dca.test', trace: 'retain-on-failure'},
  projects: ['chromium', 'webkit'].flatMap(browserName => [
    {name: `${browserName}-desktop`, use: {browserName, viewport: {width: 1280, height: 900}}},
    {name: `${browserName}-mobile`, use: {browserName, viewport: {width: 390, height: 844}, isMobile: true, hasTouch: true}},
  ]),
});
