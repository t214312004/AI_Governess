import { chromium } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
const output = new URL('../reports/g1/', import.meta.url);
const screenshotPath = name => fileURLToPath(new URL(name, output));
await mkdir(output, {recursive:true});
const browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--autoplay-policy=no-user-gesture-required'] });
const page = await browser.newPage({ viewport: {width:1280,height:1040} });
const errors = [], requests = [], consoleMessages = [];
page.on('pageerror', e => errors.push(String(e)));
page.on('console', m => { if (['warning','error'].includes(m.type())) consoleMessages.push(m.text()); });
page.on('request', r => { if (r.url().endsWith('.moc3')) requests.push(r.url()); });
page.on('response', r => { if (r.status()>=400) errors.push(`${r.status()} ${r.url()}`); });
const report = { errors, consoleMessages, requests, checks: [] };
try {
  await page.goto('http://127.0.0.1:5187/');
  await page.waitForFunction(() => window.__lab?.ready || window.__lab?.error, {timeout:30000});
  const initial = await page.evaluate(() => window.__lab);
  assert.equal(initial.error, ''); assert.equal(initial.ready,true);
  assert.ok(initial.parameters.includes('ParamMouthOpenY'));
  assert.ok(initial.parameters.includes('ParamAngleX'));
  await page.waitForTimeout(2000);
  const canvasPixels = await page.locator('canvas').evaluate(canvas => {
    const gl=canvas.getContext('webgl'); const pixels=new Uint8Array(canvas.width*canvas.height*4);
    gl.readPixels(0,0,canvas.width,canvas.height,gl.RGBA,gl.UNSIGNED_BYTE,pixels);
    let alpha=0; for(let i=3;i<pixels.length;i+=4) if(pixels[i]>20) alpha++;
    return alpha;
  });
  assert.ok(canvasPixels > 10000, `Model not rendered: ${canvasPixels} visible pixels`);
  report.visiblePixels = canvasPixels;
  await page.screenshot({path:screenshotPath('governess-preview.png'), fullPage:true});
  report.checks.push('own character moc consistency + visible WebGL pixels');
  for(const from of ['IDLE_LISTEN','COLLECTING','SENDING','SPEAKING','HOT_LISTEN']) {
    for(const to of ['IDLE_LISTEN','COLLECTING','SENDING','SPEAKING','HOT_LISTEN']) {
      if(from===to) continue;
      await page.locator(`[data-state="${from}"]`).click();
      await page.locator(`[data-state="${to}"]`).click();
      assert.equal(await page.evaluate(()=>window.__lab.state),to);
    }
  }
  assert.equal(requests.length,1); report.checks.push('all 20 state transitions reuse one moc instance');
  report.mouthDeformation = await page.evaluate(()=>window.__labProbeMouth());
  assert.ok(report.mouthDeformation.count > 0 && report.mouthDeformation.maxDelta > 1e-6);
  await page.locator('#mouth').fill('1');
  await page.waitForFunction(()=>window.__lab.modelMouth===1);
  report.checks.push('mouth parameter reaches Core and mouth mesh vertices deform');
  await page.screenshot({path:screenshotPath('mouth-open.png'),fullPage:true});
  await page.locator('#mouth').fill('0');
  await page.evaluate(()=>document.querySelector('audio').play());
  await page.waitForFunction(()=>window.__lab.modelMouth>0.05);
  report.checks.push('audio signal opens mouth');
  await page.evaluate(()=>document.querySelector('audio').pause());
  await page.waitForFunction(()=>window.__lab.mouth===0);
  await page.evaluate(()=>document.querySelector('audio').play());
  await page.waitForFunction(()=>window.__lab.mouth>0.05);
  await page.evaluate(()=>document.querySelector('audio').muted=true);
  await page.waitForFunction(()=>window.__lab.mouth===0);
  await page.locator('#stop').click();
  assert.equal(await page.evaluate(()=>document.querySelector('audio').currentTime),0);
  report.checks.push('pause, mute and stop close mouth');
  report.governess = await page.evaluate(()=>{ const {mouthVertices,...rest}=window.__lab; return rest; });
  await page.locator('#model').selectOption('compatibility');
  await page.waitForFunction(()=>window.__lab.ready && window.__lab.loads===2);
  await page.waitForTimeout(1000);
  report.compatibility = await page.evaluate(()=>{ const {mouthVertices,...rest}=window.__lab; return rest; });
  report.checks.push('official fixture exported by PSD2Live loads in Core');
  await page.screenshot({path:screenshotPath('compatibility-preview.png'),fullPage:true});
  await page.goto('http://127.0.0.1:5187/arms.html');
  await page.waitForFunction(()=>window.__armLab?.ready || window.__armLab?.error);
  assert.equal(await page.evaluate(()=>window.__armLab.error),'');
  const armLoads=requests.length;
  report.armSamples=[];
  for(const value of [0,.25,.5,.75,1]) {
    await page.locator('#transition').fill(String(value));
    await page.waitForTimeout(1000);
    const sample=await page.evaluate(()=>window.__armLab);
    assert.equal(sample.loads,1);
    assert.equal(Object.keys(sample.meshBounds).length,3);
    assert.ok(Object.values(sample.meshBounds).flat().every(Number.isFinite));
    report.armSamples.push({value,...sample});
    await page.screenshot({path:screenshotPath(`arm-transition-${value}.png`),fullPage:true});
  }
  assert.equal(requests.length,armLoads);
  assert.notDeepEqual(report.armSamples[0].meshBounds,report.armSamples[4].meshBounds);
  report.checks.push('segmented arm model renders finite moving meshes across five transition samples without reload');
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({checks:report.checks,errors:report.errors,modelRequests:requests.length,mouthDeformation:report.mouthDeformation,armSamples:report.armSamples.length},null,2));
} catch(error) {
  report.failure = String(error); console.error(JSON.stringify(report,null,2));
  await page.screenshot({path:screenshotPath('failure.png'),fullPage:true});
  process.exitCode = 1;
} finally { await writeFile(new URL('browser-results.json',output),JSON.stringify(report,null,2)); await browser.close(); }
