import test from 'node:test';
import assert from 'node:assert/strict';
import {fitEyeAffine} from '../tools/eye-affine.mjs';

test('blink measurement recovers source coordinates under eye rotation and unequal scale',()=>{
  const source=[360,410,470,410,360,480,470,480,415,445];
  // Quarter-turn, unequal scale and translation: x'=1000-2y, y'=0.5x+100.
  const destination=[180,280,180,335,40,280,40,335,110,307.5];
  const fit=fitEyeAffine(source,destination);
  assert.ok(fit.maxError<1e-8);
  // Independent half-closed points, not used to fit the transformation.
  const closed=[380,455,450,460],formed=[90,290,80,325];
  fit.inverse(formed).forEach((value,i)=>assert.ok(Math.abs(value-closed[i])<1e-8));
});

test('collapsed or collinear geometry cannot silently validate blink paths',()=>{
  assert.throws(()=>fitEyeAffine([0,0,1,1,2,2],[0,0,1,1,2,2]),/Degenerate/);
  assert.throws(()=>fitEyeAffine([0,0,1,0,0,1],[0,0,0,0,0,0]),/Collapsed/);
});
