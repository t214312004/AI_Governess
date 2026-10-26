"""Execute the actual injected audio bridge to test user volume versus ducking."""
import shutil
import subprocess

import pytest

from ui.html_whiteboard import HTML_AUDIO_BRIDGE


def test_live_base_volume_survives_bridge_polling_duck_mute_and_restore():
    node=shutil.which('node')
    if not node:pytest.skip('Node is required for the JavaScript bridge contract test')
    harness=r'''
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
const script=fs.readFileSync(0,'utf8');
const media={volume:.6},timers=[];let level=1;
const sandbox={console,Map,Set,WeakMap,Number,Math,Array,encodeURIComponent,
 document:{createElement:()=>({style:{setProperty(){}},setAttribute(){}}),
 documentElement:{appendChild(){}},querySelectorAll:()=>[media]},
 fetch:async path=>({ok:true,json:async()=>path.includes('/audio')?{volume:level}:{events:[],pressed:[],sequence:0}})};
sandbox.window={addEventListener(){},setInterval:fn=>timers.push(fn)};
vm.runInNewContext(script,sandbox);
const api=sandbox.window,near=(actual,wanted)=>assert.ok(Math.abs(actual-wanted)<1e-10,`${actual} != ${wanted}`);
(async()=>{
 await Promise.resolve();await Promise.resolve();
 api.__aiGovernessSetMediaVolume(media,.25);
 for(let i=0;i<5;i++)await timers[0]();
 near(media.volume,.25);
 level=.2;await timers[0]();near(media.volume,.05);
 api.__aiGovernessSetMediaVolume(media,.8);near(media.volume,.16);
 level=0;await timers[0]();near(media.volume,0);
 api.__aiGovernessSetMediaVolume(media,.4);near(media.volume,0);
 level=1;for(let i=0;i<5;i++)await timers[0]();near(media.volume,.4);
 api.__aiGovernessSetMediaVolume(media,0);await timers[0]();near(media.volume,0);
 api.__aiGovernessSetMediaVolume(media,1);await timers[0]();near(media.volume,1);
 console.log('volume/duck/mute/restore passed');
})().catch(e=>{console.error(e);process.exitCode=1});
'''
    script=HTML_AUDIO_BRIDGE.split('<script>',1)[1].rsplit('</script>',1)[0]
    result=subprocess.run([node,'-e',harness],input=script,text=True,capture_output=True,timeout=10,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert result.returncode==0,result.stdout+result.stderr
    assert 'passed' in result.stdout
