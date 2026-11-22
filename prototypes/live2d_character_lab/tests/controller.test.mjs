import { test } from 'node:test';
import assert from 'node:assert/strict';
import { STATES, StateController, rmsToMouth, approachMouth } from '../viewer/controller.mjs';
test('all 20 directed transitions settle into the latest state without queued callbacks', () => {
  for (const from of Object.keys(STATES)) for (const to of Object.keys(STATES)) {
    if (from === to) continue;
    const controller = new StateController(); controller.set(from);
    for (let i=0;i<120;i++) controller.tick(1/60);
    const previous = { ...controller.current }; controller.set(to); controller.tick(1/60);
    assert.ok(Math.abs(controller.current.angle - previous.angle) < 1);
    for (let i=0;i<180;i++) controller.tick(1/60);
    assert.ok(Math.abs(controller.current.angle - STATES[to].angle) < .001);
    assert.equal(controller.state, to);
  }
});
test('silence, muted volume and empty buffers close the mouth', () => {
  assert.equal(rmsToMouth(new Float32Array(1024)),0);
  assert.equal(rmsToMouth(new Float32Array([.5,-.5]),0),0);
  assert.equal(rmsToMouth(new Float32Array()),0);
  assert.equal(rmsToMouth(new Float32Array([1,-1])),1);
});
test('mouth smoothing is time based and remains bounded', () => {
  let fast=0, slow=0;
  for(let i=0;i<60;i++) fast=approachMouth(fast,.7,1/60);
  for(let i=0;i<30;i++) slow=approachMouth(slow,.7,1/30);
  assert.ok(Math.abs(fast-slow)<1e-6);
  assert.ok(fast >= 0 && fast <= 1);
  assert.throws(()=>new StateController().set('INVALID'));
});
