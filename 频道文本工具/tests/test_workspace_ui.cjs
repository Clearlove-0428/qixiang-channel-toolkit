const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const tool=path.resolve(__dirname,'..');
(async()=>{
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'qixiang-workspace-test-'));
 const server=spawn(process.env.PYTHON || (process.platform==='win32'?'python':'python3'),[path.join(tool,'research_library.py'),'--root',temp,'serve','--port','18879','--no-browser'],{windowsHide:true});
 const browser=await chromium.launch({channel:process.env.QIXIANG_TEST_BROWSER_CHANNEL||'msedge',headless:true});
 try{
  for(let i=0;i<40;i++){try{if((await fetch('http://127.0.0.1:18879/api/state')).ok)break;}catch{}await new Promise(r=>setTimeout(r,150));}
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  await page.goto('http://127.0.0.1:18879');
  await page.getByText('资料已就绪，正式采集等你开始。').waitFor();
  await page.locator('#withImages').uncheck();
  const fixture={posts:[{id:'B_ui_one',text:'合成求助：校园卡办理 <img src=x onerror="window.BAD=true">',preview_only:true},{id:'B_ui_two',text:'合成学习经验'}],observations:[]};
  const file=path.join(temp,'fixture.json');fs.writeFileSync(file,JSON.stringify(fixture));
  await page.locator('#importFile').setInputFiles(file);
  await page.getByText('本批导入完成，资料已合并保存').waitFor();
  await page.locator('nav button[data-tab="posts"]').click();
  await page.locator('#listCount').filter({hasText:'共 2 帖'}).waitFor();
  assert.equal(await page.evaluate(()=>window.BAD),undefined);
  await page.getByText('填写复核',{exact:true}).first().click();
  await page.locator('#mainCategory').selectOption('校园办事');
  await page.locator('[name="reviewer"]').fill('合成测试员');
  await page.getByText('保存复核',{exact:true}).click();
  await page.getByText('已保存到本地资料库。').waitFor();
  await page.locator('#closeDialog').click();
  await page.locator('#importFile').setInputFiles(file);
  await page.waitForTimeout(1700);
  const summary=await (await fetch('http://127.0.0.1:18879/api/state')).json();
  assert.equal(summary.total_posts,2);assert.equal(summary.reviewed['正式'],1);
  const denied=await fetch('http://127.0.0.1:18879/api/annotate',{method:'POST',headers:{'Content-Type':'application/json','Origin':'http://example.invalid'},body:'{}'});
  assert.equal(denied.status,403);
  await page.locator('nav button[data-tab="research"]').click();
  await page.locator('#analysisExport').click();
  await page.locator('#analysisStatus').filter({hasText:'正式 2 帖'}).waitFor();
  const evidence=process.env.QIXIANG_TEST_OUTPUT;
  if(evidence){fs.mkdirSync(evidence,{recursive:true});await page.screenshot({path:path.join(evidence,'workspace.png'),fullPage:true});}
  console.log('本地管理页：导入、跨批去重、保存复核、重复导入、同源限制均通过（合成资料）。');
 }finally{
  await browser.close();if(server.exitCode===null){server.kill();await new Promise(r=>server.once('exit',r));}
  if(path.resolve(temp).startsWith(path.resolve(os.tmpdir())+path.sep)&&path.basename(temp).startsWith('qixiang-workspace-test-'))fs.rmSync(temp,{recursive:true,force:true});
 }
})().catch(error=>{console.error(error);process.exitCode=1;});
