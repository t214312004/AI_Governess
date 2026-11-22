import { chromium } from 'playwright';
import { mkdir,writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import catalog from '../design/feature-catalog.json' with {type:'json'};
const directory=new URL('../reports/g2/',import.meta.url);await mkdir(directory,{recursive:true});
const browser=await chromium.launch({channel:'msedge',headless:true});
const page=await browser.newPage({viewport:{width:1280,height:1100}});
const errors=[],requests=[];page.on('pageerror',e=>errors.push(String(e)));page.on('request',r=>{if(r.url().endsWith('.moc3'))requests.push(r.url());});
page.on('response',r=>{if(r.status()>=400)errors.push(`${r.status()} ${r.url()}`);});
const report={errors,requests,samples:[],handSamples:[]};
try{
  await page.goto('http://127.0.0.1:5187/fidelity.html');
  await page.waitForFunction(()=>window.__fidelity?.ready||window.__fidelity?.error);
  assert.equal(await page.evaluate(()=>window.__fidelity.error),'');
  const initialized=await page.evaluate(()=>window.__fidelity);
  assert.ok(initialized.drawables>=72,'Stale or incomplete model');assert.ok(initialized.parameters.includes('ParamReferenceFrame'));
  for(const expression of Object.values(catalog.unique_frames)){
    await page.locator('#expression').selectOption(expression);await page.waitForFunction(value=>window.__fidelity.source===value,expression);await page.waitForTimeout(250);
    for(const region of ['face']){
      await page.locator('#region').selectOption(region);await page.waitForTimeout(250);
      const sample=await page.evaluate(()=>{window.__measureFidelity();return window.__fidelity;});
      assert.ok(Number.isFinite(sample.mae));assert.equal(sample.loads,1);assert.equal(Object.keys(sample.roiMae).length,4);report.samples.push({expression,region,...sample});
    }
    await page.locator('#region').selectOption('face');await page.locator('#mode').selectOption('model');await page.waitForTimeout(250);
    await page.screenshot({path:fileURLToPath(new URL(`face-${expression}.png`,directory)),fullPage:true});
    await page.locator('#mode').selectOption('difference');await page.screenshot({path:fileURLToPath(new URL(`face-${expression}-difference.png`,directory)),fullPage:true});
  }
  assert.deepEqual(errors,[]);assert.equal(requests.length,1);
  if(!process.argv.includes('--faces-only')) {
  await page.goto('http://127.0.0.1:5187/hands.html');
  await page.waitForFunction(()=>window.__hands?.ready||window.__hands?.error);
  assert.equal(await page.evaluate(()=>window.__hands.error),'');
  for(const gesture of ['index','chin','index']) {
    await page.locator('#gesture').selectOption(gesture);await page.waitForFunction(value=>window.__hands.source===(value==='index'?'speaking_1':'sending_1'),gesture);await page.waitForTimeout(500);
    const sample=await page.evaluate(()=>{window.__measureHands();return window.__hands;});
    assert.equal(sample.loads,1);assert.equal(sample.visibleMeshes.length,1);assert.ok(sample.interiorPixels>10000);assert.ok(Number.isFinite(sample.rgbMae));
    report.handSamples.push({gesture,...sample});
    await page.locator('#mode').selectOption('model');
    await page.screenshot({path:fileURLToPath(new URL(`hand-${gesture}.png`,directory)),fullPage:true});
    await page.locator('#mode').selectOption('overlay');
    await page.screenshot({path:fileURLToPath(new URL(`hand-${gesture}-overlay.png`,directory)),fullPage:true});
  }
  assert.deepEqual(errors,[]);assert.equal(requests.length,2);assert.equal(requests[0],requests[1]);
  }
}catch(error){report.failure=String(error);process.exitCode=1;}
finally{await writeFile(new URL('fidelity-results.json',directory),JSON.stringify(report,null,2));await browser.close();}
console.log(JSON.stringify({...report,samples:report.samples.map(({expression,region,mae,roiMae})=>({expression,region,mae,roiMae}))},null,2));
