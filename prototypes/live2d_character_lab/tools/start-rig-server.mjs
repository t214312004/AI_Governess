import { spawn } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { mkdirSync, writeFileSync, openSync } from 'node:fs';
import { resolve } from 'node:path';
import {createServer} from 'node:net';
const root=resolve(import.meta.dirname,'..');
// Never replace a running service's credential with a new, unusable token.
const available=await new Promise((resolve,reject)=>{const probe=createServer();probe.once('error',error=>error.code==='EADDRINUSE'?resolve(false):reject(error));probe.listen(23872,'127.0.0.1',()=>probe.close(()=>resolve(true)));});
if(!available){console.log('Port 23872 is already in use; existing credentials were preserved.');process.exit(0);}
mkdirSync(`${root}/.cache/rig-store`,{recursive:true});
const token=randomBytes(32).toString('hex');
writeFileSync(`${root}/.cache/rig-connection.json`,JSON.stringify({endpoint:'http://127.0.0.1:23872/mcp',token}));
const log=openSync(`${root}/.cache/rig-server.log`,'w');
const child=spawn(`${root}/vendor/psd2live/PSD2Live.exe`,['mcp','--port','23872','--store',`${root}/.cache/rig-store`,'--token',token],{windowsHide:true,stdio:['ignore',log,log]});
console.log('PSD2Live authoring service starting on localhost:23872; credentials stay in .cache.');
child.on('exit',code=>{process.exitCode=code??1;});
process.on('SIGINT',()=>child.kill());
