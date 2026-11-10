const {test,expect}=require('playwright/test');
const {spawn}=require('node:child_process');
const {once}=require('node:events');
const path=require('node:path');

test.use({ignoreHTTPSErrors:true});
test('real HTTPS setup, rejected purchase and successful recovery reach the browser',async({page})=>{
  test.setTimeout(60000);
  const child=spawn(process.env.PYTHON||'python3',['-m','tests.browser.live_server'],{
    cwd:path.resolve(__dirname,'../..'),stdio:['ignore','pipe','pipe']
  });
  let stderr='';child.stderr.on('data',chunk=>stderr+=chunk);
  try{
    const url=await new Promise((resolve,reject)=>{
      let output='';
      const timer=setTimeout(()=>reject(Error('HTTPS fixture did not start: '+stderr)),20000);
      child.once('error',error=>{clearTimeout(timer);reject(error)});
      child.once('exit',code=>{clearTimeout(timer);reject(Error('HTTPS fixture exited '+code+': '+stderr))});
      child.stdout.on('data',chunk=>{output+=chunk;const end=output.indexOf('\n');if(end>=0){clearTimeout(timer);resolve(JSON.parse(output.slice(0,end)).url)}});
    });
    expect((await page.request.get(url+'/api/schedule')).status()).toBe(401);
    await page.goto(url);
    await page.locator('#newUsername').fill('browser-operator');
    await page.locator('#newPassword').fill('browser-test-password');
    await page.locator('#confirmPassword').fill('browser-test-password');
    await page.locator('#accountForm button').click();
    await expect(page.locator('#settingsForm')).toBeVisible();
    const save=settings=>page.request.post(url+'/api/settings',{
      headers:{'X-DCA-Action':'settings'},data:{settings}
    });
    const configured=await save({kraken_api_key:'offline-key',kraken_api_secret:'b2ZmbGluZQ==',
      live:true,startup_delay_seconds:0,order_status_check_seconds:1,check_interval_seconds:60,dashboard_refresh_seconds:5});
    expect(configured.ok()).toBe(true);
    await expect.poll(async()=>{
      const response=await page.request.get(url+'/api/schedule');return (await response.json()).nextPurchaseStatusCode;
    }).toBe('purchase_rejected');
    await page.goto(url);
    await expect(page.locator('#botStatusLight')).toHaveClass(/status-error/);
    await expect(page.locator('#nextPurchaseAt')).toContainText('Purchase rejected');
    expect(await page.locator('body').innerText()).not.toContain('PRIVATE EXCHANGE DETAIL');
    expect((await save({buy_amount:'.0002'})).ok()).toBe(true);
    await expect.poll(async()=>{
      const response=await page.request.get(url+'/api/analytics?start=0&end='+Date.now());
      return (await response.json()).summary.buyCount;
    },{timeout:15000}).toBe(1);
    await page.evaluate(()=>refreshPurchaseSchedule());
    await expect(page.locator('#botStatusLabel')).toHaveText('Bot active');
    await expect(page.locator('#botStatusLight')).toHaveClass(/status-active/);
  }finally{
    if(child.exitCode===null){
      const exited=once(child,'exit');child.kill('SIGTERM');
      const timer=setTimeout(()=>child.kill('SIGKILL'),10000);
      await exited;clearTimeout(timer);
    }
  }
});
