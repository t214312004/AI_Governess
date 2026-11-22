import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { chromium } from 'playwright';
import utils from 'playwright-core/lib/utilsBundle';

const origin = 'http://127.0.0.1:5187';
const target = 'reports/g2/g2a';
const rig = JSON.parse(await readFile('authoring/gesture-g2a/runtime-map.json', 'utf8'));
const parts = JSON.parse(await readFile('authoring/gesture-g2a/parts.json', 'utf8'));
const art = JSON.parse(await readFile('design/gesture-g2a.json', 'utf8'));
const armFit = JSON.parse(await readFile('authoring/gesture-g2a/arm-fit.json', 'utf8'));
const meshId = name => rig[name].replace('mesh:', '');
const frame = page => page.evaluate(() => new Promise(resolve =>
  requestAnimationFrame(() => requestAnimationFrame(resolve))));
const snapshot = page => page.evaluate(() => window.__sharedSnapshot());

function bounds(vertices) {
  const x = vertices.filter((_, index) => index % 2 === 0);
  const y = vertices.filter((_, index) => index % 2 === 1);
  const [left, top] = [Math.min(...x), Math.min(...y)];
  return { left, top, width: Math.max(...x) - left, height: Math.max(...y) - top };
}

async function opaqueArtworkBounds(name) {
  const rect = parts[name];
  const png = utils.PNG.sync.read(await readFile(`authoring/gesture-g2a/${name}.png`));
  let minX = png.width, minY = png.height, maxX = -1, maxY = -1;
  for (let y = 0; y < png.height; y++) {
    for (let x = 0; x < png.width; x++) {
      if (png.data[(y * png.width + x) * 4 + 3] < 128) continue;
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
    }
  }
  return { left: rect.left + minX, top: rect.top + minY,
    width: maxX - minX + 1, height: maxY - minY + 1 };
}

function boxMirrorError(right, left) {
  const axis = art.mirrorAxis - art.coordinateOrigin[0];
  return Math.max(
    Math.abs(2 * axis - right.left - right.width - left.left),
    Math.abs(right.top - left.top),
    Math.abs(right.width - left.width),
    Math.abs(right.height - left.height),
  );
}

function projectWrist(rest, posed, [x, y]) {
  x -= art.coordinateOrigin[0];
  const v = rest.sourceVertices;
  for (let i = 0; i < rest.indices.length; i += 3) {
    const [a, b, c] = rest.indices.slice(i, i + 3).map(index => index * 2);
    const denominator = (v[b + 1] - v[c + 1]) * (v[a] - v[c]) +
      (v[c] - v[b]) * (v[a + 1] - v[c + 1]);
    if (Math.abs(denominator) < .001) continue;
    const u = ((v[b + 1] - v[c + 1]) * (x - v[c]) + (v[c] - v[b]) * (y - v[c + 1])) / denominator;
    const w = ((v[c + 1] - v[a + 1]) * (x - v[c]) + (v[a] - v[c]) * (y - v[c + 1])) / denominator;
    if (Math.min(u, w, 1 - u - w) < -.001) continue;
    const p = posed.sourceVertices;
    return [0, 1].map(axis => u * p[a + axis] + w * p[b + axis] + (1 - u - w) * p[c + axis]);
  }
  throw new Error('The wrist landmark is outside its hand mesh');
}

function imageEdge(image, y) {
  const scale = image.height / 1540;
  const row = Math.round((y - 105) * scale);
  const x = image.data.subarray(row * image.width * 4, (row + 1) * image.width * 4)
    .findIndex((value, index) => index % 4 === 3 && value >= 180);
  assert.ok(x >= 0, 'Missing elbow silhouette');
  return Math.floor(x / 4);
}

function sleeveEdge(image, start, end) {
  const edge = [];
  for (let y = start; y <= end; y += 5) edge.push(imageEdge(image, y));
  return edge;
}

function elbowReferenceError(image) {
  const { outerContour, scale, referenceElbow, canvasElbow } = art.forearm45;
  const [sx, sy] = referenceElbow;
  const [wx, wy] = canvasElbow;
  const errors = outerContour.filter(([, y]) => y >= 895 && y <= 940).map(([x, y]) => {
    const target = (wx + scale * (x - sx) - 345) * image.width / 1540;
    return Math.abs(target - imageEdge(image, wy + scale * (y - sy)));
  });
  return Math.max(...errors);
}

async function saveEndpointOverlay(page, state) {
  await page.locator('#reference-state').evaluate((select, name) => {
    select.value = name;
    select.dispatchEvent(new Event('change'));
  }, state);
  await page.waitForFunction(name => window.__sharedReference?.ready && window.__sharedReference.source === name, state);
  await page.locator('#apply-reference').evaluate(button => button.click());
  await page.locator('#reference-mode').evaluate(select => {
    select.value = 'overlay';
    select.dispatchEvent(new Event('change'));
  });
  await frame(page);

  const urls = await page.evaluate(() => {
    const model = document.querySelector('#avatar');
    const source = document.querySelector('#reference');
    const canvas = document.createElement('canvas');
    canvas.width = model.width;
    canvas.height = model.height;
    const context = canvas.getContext('2d');
    context.fillStyle = '#f5f2ee';
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(model, 0, 0);
    context.globalAlpha = .5;
    context.drawImage(source, 0, 0);
    return [model.toDataURL(), source.toDataURL(), canvas.toDataURL()];
  });
  const images = urls.map(url => Buffer.from(url.split(',')[1], 'base64'));
  await Promise.all(['model', 'original', 'overlay'].map((kind, index) =>
    writeFile(`${target}/${state}-${kind}.png`, images[index])));

  // The calibrated chin-rest elbow deliberately moves the lower sleeve join.
  const [model, source] = images.slice(0, 2).map(png => sleeveEdge(utils.PNG.sync.read(png), 905, 1165));
  const errors = model.map((x, index) => Math.abs(x - source[index]));
  return { mean: errors.reduce((sum, value) => sum + value, 0) / errors.length, max: Math.max(...errors) };
}

async function setControls(page, controls) {
  await page.evaluate(values => {
    for (const [id, value] of Object.entries(values)) {
      const input = document.getElementById(id);
      input.value = String(value);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }
  }, controls);
  await frame(page);
}

await mkdir(target, { recursive: true });
const browser = await chromium.launch({ channel: 'msedge', args: ['--autoplay-policy=no-user-gesture-required'] });
try {
  const pages = await Promise.all([browser.newPage(), browser.newPage()]);
  const [approved, gesture] = pages;
  const errors = [];
  await Promise.all(pages.map(async (page, index) => {
    page.on('pageerror', error => errors.push(String(error)));
    await page.goto(`${origin}/shared-face.html?${index ? 'gesture' : 'polish'}=1`);
    await page.waitForFunction(() => window.__shared?.ready);
  }));

  const facePoses = [
    {},
    { ParamEyeROpen: .45, ParamEyeLOpen: .45, ParamAngleX: 3, ParamAngleY: -2, ParamHeadTilt: 2, ParamMouthOpenY: .72 },
    { ParamEyeROpen: 0, ParamEyeLOpen: 0, ParamAngleX: -4, ParamAngleY: 2, ParamHeadTilt: -2, ParamMouthOpenY: .45 },
  ];
  let compared = 0;
  for (const [index, pose] of facePoses.entries()) {
    await Promise.all(pages.map(page => page.locator('[data-preset=neutral]').click()));
    await Promise.all([setControls(approved, pose), setControls(gesture, { ...pose, GestureProgress: index / 2 })]);
    const [before, after] = await Promise.all(pages.map(snapshot));
    for (const [id, mesh] of Object.entries(before.meshes)) {
      assert.deepEqual(after.meshes[id], mesh, `v11 mesh ${id} changed at pose ${index}`);
      compared++;
    }
  }

  await gesture.locator('[data-preset=neutral]').click();
  await gesture.locator('#GestureProgress').evaluate(input => input.step = 'any');
  const sidePicker = gesture.locator('#gesture-side');
  assert.ok(await sidePicker.isEnabled(), 'The model has no native side control');
  const samples = [0, .08, .16, .25, .34, .44, .46, .48, .5, .56, .67, .73, .74, .8, .88, .91, .95, 1];
  const handBounds = {};
  let maxSleeveEdgeStep = 0;
  let maxUpperSleeveEdgeSpan = 0;
  const native = (meshes, name) => meshes[meshId(name)];
  const poseAt = async progress => {
    await setControls(gesture, { GestureProgress: progress });
    return snapshot(gesture);
  };
  const save = async name => {
    const data = await gesture.locator('#avatar').evaluate(canvas => canvas.toDataURL());
    const png = Buffer.from(data.split(',')[1], 'base64');
    await writeFile(`${target}/${name}.png`, png);
    return utils.PNG.sync.read(png);
  };

  for (const progress of samples) {
    const { loads, meshes } = await poseAt(progress);
    assert.equal(loads, 1);
    const body = native(meshes, 'GestureBody');
    assert.ok(bounds(body.sourceVertices).top > 900, 'Torso moved to the face');
    for (const name of Object.keys(rig)) {
      assert.ok(native(meshes, name).sourceVertices.every(Number.isFinite), name);
    }
    for (const name of ['GestureCuff', 'GestureForearm']) {
      assert.equal(native(meshes, name).opacity, 1, `${name} fades during the arm path`);
    }
    if (progress <= .88) {
      assert.equal(native(meshes, 'GestureindexHand').opacity, 0, 'The index extends too early');
      assert.equal(native(meshes, 'GesturechinHand').opacity, 1);
    } else {
      assert.equal(native(meshes, 'GestureindexHand').opacity, 1);
    }
    if (progress >= .44 && progress <= .5) {
      assert.equal(native(meshes, 'GestureSupportBack').opacity, 1);
      assert.equal(native(meshes, 'GestureSupportFingers').opacity, 1);
      assert.equal(native(meshes, 'GestureSupportChin').opacity, 0);
      assert.equal(native(meshes, 'GestureElbowUnderlay').opacity, 0);
    }
    if (progress === 0 || progress === 1) {
      const name = progress ? 'GestureindexHand' : 'GesturechinHand';
      const measured = bounds(native(meshes, name).sourceVertices);
      const artBounds = await opaqueArtworkBounds(name);
      if (progress === 1) {
        const [dx, dy] = armFit.sides[0].pointWristShift;
        artBounds.left += dx;
        artBounds.top += dy;
      }
      for (const key of ['left', 'top', 'width', 'height']) {
        const difference = Math.abs(measured[key] - artBounds[key]);
        assert.ok(difference < 5, `${name} ${key} differs from its artwork bounds by ${difference} px`);
      }
      handBounds[name] = measured;
    }
    const image = await save(`frame-${Math.round(progress * 100)}`);
    const outline = sleeveEdge(image, 810, 1245);
    const step = Math.max(...outline.slice(1).map((x, index) => Math.abs(x - outline[index])));
    assert.ok(step <= 8, `Abrupt sleeve outline at ${progress}: ${step} px`);
    maxSleeveEdgeStep = Math.max(maxSleeveEdgeStep, step);
    const upper = sleeveEdge(image, 905, 1165);
    const widthChange = Math.max(...upper) - Math.min(...upper);
    assert.ok(widthChange <= 5, `The upper sleeve bows in or out at ${progress}: ${widthChange} px`);
    maxUpperSleeveEdgeSpan = Math.max(maxUpperSleeveEdgeSpan, widthChange);
  }

  const { pairs, liftFrames } = await gesture.evaluate(async spec => {
    const { gestureG2a } = await import('/viewer/gesture-g2a.ts');
    const angle = ([x, y], [ex, ey]) => Math.atan2(y - ey, x - ex) * 180 / Math.PI;
    const lower = angle(spec.inbetween.targetWrist, spec.chin.elbow);
    const neutral = angle(spec.chin.wrist, spec.chin.elbow);
    const find = (target, rising) => {
      let lo = rising ? spec.motion.raiseStart : 0;
      let hi = rising ? spec.motion.raiseEnd : spec.motion.lowerEnd;
      for (let i = 0; i < 38; i++) {
        const mid = (lo + hi) / 2;
        if ((gestureG2a(mid, 0).ParamGestureReach < target) === rising) lo = mid;
        else hi = mid;
      }
      return (lo + hi) / 2;
    };
    const pairs = [18, 30, spec.motion.lift.startDegrees].map(degrees => {
      const reach = (-degrees - lower) / (neutral - lower);
      return { degrees, down: find(reach, false), up: find(reach, true) };
    });
    const liftFrames = Array.from({ length: 41 }, (_, i) => {
      const t = i / 40;
      return find(spec.motion.lift.keyStart + t, true);
    });
    return { pairs, liftFrames };
  }, art);

  let maxSameAngleDifference = 0;
  let maxMirrorBoundsError = 0;
  const pairData = [];
  for (const { degrees, down, up } of pairs) {
    const downPose = await poseAt(down);
    await save(`angle-${degrees}-down`);
    const upPose = await poseAt(up);
    const image = await save(`angle-${degrees}-up`);
    if (degrees === 45) {
      assert.ok(elbowReferenceError(image) < 6, 'The 45-degree elbow still indents');
    }
    let matched = 0;
    for (const name of ['GesturechinHand', 'GestureForearm', 'GestureCuff']) {
      const a = native(downPose.meshes, name);
      const b = native(upPose.meshes, name);
      assert.equal(a.opacity, 1);
      assert.equal(b.opacity, 1);
      matched = Math.max(matched, ...a.sourceVertices.map((x, index) => Math.abs(x - b.sourceVertices[index])));
    }
    assert.ok(matched < .05, `Mesh changes size or shape at the same ${degrees}° angle: ${matched}`);
    maxSameAngleDifference = Math.max(maxSameAngleDifference, matched);
    await sidePicker.selectOption('1');
    const left = await poseAt(up);
    assert.equal(left.loads, 1, 'Switching arms loaded another model');
    for (const name of ['GesturechinHand', 'GestureForearm', 'GestureCuff']) {
      assert.equal(native(left.meshes, name).opacity, 0);
      assert.equal(native(left.meshes, name + 'Left').opacity, 1);
      const error = boxMirrorError(bounds(native(upPose.meshes, name).sourceVertices),
        bounds(native(left.meshes, name + 'Left').sourceVertices));
      assert.ok(error < 6, `Mirrored ${name} drifted at ${degrees}°: ${error}`);
      maxMirrorBoundsError = Math.max(maxMirrorBoundsError, error);
    }
    await save(`angle-${degrees}-left`);
    await sidePicker.selectOption('0');
    pairData.push({ degrees, down, up, meshDifference: matched });
  }

  const liftChecks = [];
  const displayScale = 900 / 1540;
  const distance = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]) * displayScale;
  const targetForearm = armFit.forearmLength * displayScale;
  const targetUpperArm = armFit.shoulderSpan * art.handAnthropometry.ansurUpperArmLengthMm /
    art.handAnthropometry.ansurShoulderBreadthMm * displayScale;
  for (const side of [0, 1]) {
    await sidePicker.selectOption(String(side));
    const suffix = side ? 'Left' : '';
    const origin = (point) => side ? [2 * art.mirrorAxis - point[0], point[1]] : point;
    const restMeshes = (await poseAt(0)).meshes;
    const restElbow = origin(art.chin.elbow).map((value, axis) => value + armFit.sides[side].chinElbowShift[axis]);
    const shoulder = origin([art.handAnthropometry.shoulderMarkers[0], art.handAnthropometry.shoulderHeight]);
    shoulder[0] -= art.coordinateOrigin[0];
    const measureArm = async progress => {
      const { meshes } = await poseAt(progress);
      const mark = (name, point) => projectWrist(native(restMeshes, name + suffix), native(meshes, name + suffix), point);
      const elbow = mark('GestureCuff', restElbow);
      const wrist = mark('GesturechinHand', origin(art.chin.palmLandmarks.wrist));
      const knuckles = mark('GesturechinHand', origin(art.chin.palmLandmarks.knuckles));
      return { progress, elbow, wrist, forearmLength: distance(elbow, wrist),
        upperArmLength: distance(shoulder, elbow), palmLength: distance(wrist, knuckles) };
    };
    const measurements = [];
    for (const progress of liftFrames) measurements.push(await measureArm(progress));
    const fullPath = [];
    for (const progress of samples) fullPath.push(await measureArm(progress));
    const center = measurements.at(-1).elbow;
    const radii = measurements.map(frame => distance(center, frame.wrist));
    const radiusSpread = Math.max(...radii) - Math.min(...radii);
    const maxElbowDrift = Math.max(...measurements.map(frame => distance(center, frame.elbow)));
    const angles = measurements.map(({ wrist: [x, y] }) =>
      Math.atan2(center[1] - y, (x - center[0]) * (side ? -1 : 1)) * 180 / Math.PI);
    const angularSweep = angles.at(-1) - angles[0];
    const maxPalmDeviation = Math.max(...measurements.map(frame => Math.abs(frame.palmLength - measurements[0].palmLength)));
    const maxForearmError = Math.max(...fullPath.map(frame => Math.abs(frame.forearmLength - targetForearm)));
    assert.ok(maxForearmError < 2, `Forearm projects at the wrong anatomical length: ${maxForearmError} px`);
    assert.ok(fullPath.every(({ upperArmLength }) => upperArmLength / targetUpperArm >= .88 &&
      upperArmLength / targetUpperArm <= 1.08), 'Shoulder-to-elbow projection exceeds the fitted body proportions');
    assert.ok(radiusSpread < 1, `The wrist arc radius varies by ${radiusSpread} px`);
    assert.ok(maxElbowDrift < 1, `The elbow drifts by ${maxElbowDrift} px during the wrist arc`);
    assert.ok(angularSweep > 35 && angles.every((angle, i) => i === 0 || angle > angles[i - 1]),
      `The wrist does not sweep continuously through the arc: ${angularSweep}°`);
    assert.ok(maxPalmDeviation < .3, `Palm length changes on the lift: ${maxPalmDeviation} px`);
    liftChecks.push({ side, radius: radii.at(-1), radiusSpread, maxElbowDrift, angularSweep,
      maxPalmDeviation, maxForearmError, measurements, fullPath });

    const before = await poseAt(art.motion.pointStart);
    await save(side ? 'point-before-left' : 'point-before-right');
    const blend = await poseAt(art.motion.pointStart + art.motion.pointBlend / 2);
    await save(side ? 'point-blend-left' : 'point-blend-right');
    const extension = await poseAt(.91);
    const atEnd = await poseAt(1);
    const hand = 'GestureindexHand' + suffix;
    assert.equal(native(before.meshes, hand).opacity, 0);
    assert.ok(native(blend.meshes, hand).opacity > 0 && native(blend.meshes, hand).opacity < 1);
    assert.equal(native(atEnd.meshes, hand).opacity, 1);
    for (const piece of ['Cuff', 'Forearm']) {
      const name = 'Gesture' + piece + suffix;
      const settled = native(before.meshes, name);
      for (const frame of [before, blend, extension, atEnd]) {
        const current = native(frame.meshes, name);
        assert.equal(current.opacity, 1);
        assert.deepEqual(current.sourceVertices, settled.sourceVertices, `${name} shifts as the index finger extends`);
      }
    }
    await save(side ? 'point-left' : 'point-right');
  }
  await sidePicker.selectOption('0');
  const fit = JSON.parse(await readFile('authoring/gesture-g2a/palm-fit.json', 'utf8'));
  const palmWidthDifference = Math.abs(fit.measuredWidths.chin - fit.measuredWidths.index);
  assert.ok(palmWidthDifference <= 3, `Hand-size fitting still jumps at the pointing transition: ${palmWidthDifference}`);
  const knuckleWidthDifference = Math.abs(fit.measuredKnuckles.chin - fit.measuredKnuckles.index);
  assert.ok(knuckleWidthDifference <= 3, `The finger bases change width at the pointing transition: ${knuckleWidthDifference}`);

  const rest = (await poseAt(0)).meshes;
  const beforePoint = (await poseAt(art.motion.pointStart)).meshes;
  const straight = (await poseAt(1)).meshes[meshId('GestureindexHand')];
  const wristChin = projectWrist(native(rest, 'GesturechinHand'), native(beforePoint, 'GesturechinHand'), art.chin.palmLandmarks.wrist);
  const indexWrist = art.index.palmLandmarks.wrist.map((value, axis) => value + armFit.sides[0].pointWristShift[axis]);
  const wristPoint = projectWrist(native(rest, 'GestureindexHand'), straight, indexWrist);
  const wristSwitchPixels = Math.hypot(...wristChin.map((value, index) => value - wristPoint[index])) * 900 / 1540;
  assert.ok(wristSwitchPixels < 2, `The wrist shifts at the switch to pointing: ${wristSwitchPixels} canvas pixels`);
  await poseAt(1);
  await setControls(gesture, { GestureFlex: 1 });
  const bent = (await snapshot(gesture)).meshes[meshId('GestureindexHand')];
  assert.notDeepEqual(bent.sourceVertices, straight.sourceVertices);
  const endpointEdgeError = {
    chin: await saveEndpointOverlay(gesture, 'sending_1'),
    index: await saveEndpointOverlay(gesture, 'speaking_1'),
  };
  for (const [pose, error] of Object.entries(endpointEdgeError)) {
    assert.ok(error.mean < 3 && error.max <= 7, `Sleeve edge is offset at the ${pose} endpoint: ${JSON.stringify(error)}`);
  }
  const chestChecks = [];
  const poseSelector = gesture.locator('#gesture-target');
  assert.ok(await poseSelector.isEnabled(), 'The same model has no chest gesture');
  const palmStart = art.chest.motion.palmStart;
  const beforePalm = (art.motion.raiseEnd + palmStart) / 2;
  const midOpening = palmStart + art.chest.motion.unfoldSpan / 2;
  const chestSamples = [0, .12, .16, .28, .31, .44, .48, .52, .6, .68, .78, .87, beforePalm, palmStart, midOpening, 1];
  const originalAtCross = (await poseAt(art.motion.raiseStart)).meshes;
  await poseSelector.selectOption('chest');
  assert.ok(await gesture.locator('#GestureFlex').isDisabled());
  const chestAtCross = (await poseAt(art.motion.raiseStart)).meshes;
  for (const part of ['GestureCuff', 'GestureForearm', 'GesturechinHand']) {
    const drift = Math.max(...native(chestAtCross, part).sourceVertices.map((value, i) =>
      Math.abs(value - native(originalAtCross, part).sourceVertices[i])));
    assert.ok(drift < .05, `${part} jumps as the chest route leaves the crossed pose`);
  }
  for (const side of [0, 1]) {
    await sidePicker.selectOption(String(side));
    const suffix = side ? 'Left' : '';
    const restMeshes = (await poseAt(0)).meshes;
    const mirror = ([x, y]) => [side ? 2 * art.mirrorAxis - x : x, y];
    const chinElbow = mirror(art.chin.elbow).map((value, i) => value + armFit.sides[side].chinElbowShift[i]);
    const chestWrist = mirror(art.chest.palmLandmarks.wrist).map((value, i) => value + armFit.sides[side].chestWristShift[i]);
    let beforeSwitch, closedAtSwitch, maxForearmError = 0, maxWristGap = 0, chestWristDisplacement, palmLengthChange;
    let foldedPalm;
    for (const progress of chestSamples) {
      const { loads, meshes, renderOrders } = await poseAt(progress);
      const part = name => native(meshes, name + suffix);
      const order = name => renderOrders[meshId(name + suffix)];
      assert.equal(loads, 1);
      assert.equal(part('GestureindexHand').opacity, 0);
      assert.equal(native(meshes, 'GestureChestHand' + (side ? '' : 'Left')).opacity, 0);
      for (const name of ['GestureSupportBack', 'GestureSupportFingers', 'GestureChestSleeveBridge']) {
        assert.equal(part(name).opacity, 1, `${name} fades during the chest route`);
      }
      for (const name of ['GestureSupportChin', 'GestureSupport', 'GestureElbowUnderlay']) {
        assert.equal(part(name).opacity, 0, `${name} produces an extra contour during the chest route`);
      }
      for (const name of ['GestureCuff', 'GestureForearm', 'GesturechinHand', 'GestureChestHand']) {
        assert.ok(order('GestureSupportBack') < order(name) && order(name) < order('GestureSupportFingers'),
          `The supporting hand covers the wrong layer at ${progress}: ${name}`);
      }
      const placed = (name, marker) => projectWrist(native(restMeshes, name + suffix), native(meshes, name + suffix), marker);
      const elbow = placed('GestureCuff', chinElbow);
      const closedWrist = placed('GesturechinHand', mirror(art.chin.palmLandmarks.wrist));
      const chestPalm = part('GestureChestHand');
      assert.equal(chestPalm.opacity, Number(progress >= palmStart));
      assert.equal(part('GesturechinHand').opacity, Number(progress < palmStart));
      if (progress === beforePalm) {
        beforeSwitch = meshes;
        closedAtSwitch = closedWrist;
      }
      if (progress === palmStart) foldedPalm = chestPalm;
      if (progress === midOpening) assert.notDeepEqual(chestPalm.sourceVertices, foldedPalm.sourceVertices);
      if (progress >= palmStart) {
        for (const name of ['GestureCuff' + suffix, 'GestureForearm' + suffix]) {
          assert.deepEqual(native(meshes, name).sourceVertices, native(beforeSwitch, name).sourceVertices);
        }
      }
      const wrist = progress >= palmStart ? placed('GestureChestHand', chestWrist) : closedWrist;
      const { sourceVertices: forearm, indices: skinTriangles } = part('GestureForearm');
      let wristGap = Infinity;
      for (let i = 0; i < skinTriangles.length; i++) {
        const a = 2 * skinTriangles[i];
        const b = 2 * skinTriangles[i % 3 === 2 ? i - 2 : i + 1];
        const dx = forearm[b] - forearm[a], dy = forearm[b + 1] - forearm[a + 1];
        const span = dx * dx + dy * dy;
        if (!span) continue;
        const t = Math.max(0, Math.min(1, ((wrist[0] - forearm[a]) * dx + (wrist[1] - forearm[a + 1]) * dy) / span));
        wristGap = Math.min(wristGap, distance(wrist, [forearm[a] + t * dx, forearm[a + 1] + t * dy]));
      }
      maxWristGap = Math.max(maxWristGap, wristGap);
      // The cut edge sits inside the overlapping palm to hide its outline during the hand change.
      assert.ok(wristGap < 17, `Forearm edge extends beyond the palm overlap at ${progress}: ${wristGap} px`);
      maxForearmError = Math.max(maxForearmError, Math.abs(distance(elbow, wrist) - targetForearm));
      if (progress === 1) {
        assert.notDeepEqual(chestPalm.sourceVertices, foldedPalm.sourceVertices);
        chestWristDisplacement = distance(wrist, closedAtSwitch);
        assert.ok(chestWristDisplacement < 2, `Chest hand jumps by ${chestWristDisplacement} px`);
        const knuckles = mirror(art.chest.palmLandmarks.knuckles).map((value, i) => value + armFit.sides[side].chestWristShift[i]);
        const foldedWrist = projectWrist(chestPalm, foldedPalm, chestWrist);
        const foldedKnuckles = projectWrist(chestPalm, foldedPalm, knuckles);
        const openKnuckles = projectWrist(chestPalm, chestPalm, knuckles);
        palmLengthChange = Math.abs(distance(foldedWrist, foldedKnuckles) - distance(wrist, openKnuckles));
        assert.ok(palmLengthChange < 3, `Unfolding scales the palm by ${palmLengthChange} px`);
      }
      if (progress === 1 || (!side && [.16, .31, .44, .68, beforePalm, palmStart, midOpening].includes(progress))) {
        await save(`chest-${side ? 'left' : 'right'}-${Math.round(progress * 100)}`);
      }
    }
    assert.ok(maxForearmError < 2, `Chest forearm does not keep its calibrated length: ${maxForearmError} px`);
    chestChecks.push({ side, samples: chestSamples.length, maxForearmError, maxWristGap, chestWristDisplacement, palmLengthChange,
      stableSupportOrder: true, opaquePalmSwap: true });
  }
  const chestEndpointEdgeError = await saveEndpointOverlay(gesture, 'speaking_3');
  assert.equal(await poseSelector.inputValue(), 'chest');
  assert.equal((await snapshot(gesture)).loads, 1);
  for (const route of ['point', 'chest']) {
    await gesture.locator('#stop').click();
    await poseSelector.selectOption(route);
    await setControls(gesture, { GestureProgress: 0, GestureFlex: 0 });
    await gesture.locator('#gesture-motion').click();
    await gesture.locator('#audio').evaluate(audio => audio.play());
    await gesture.waitForFunction(() => {
      const { values, audioDriven } = window.__shared;
      return audioDriven && values.ParamMouthOpenY > .12 && values.GestureProgress > .03 && values.GestureProgress < 1;
    });
    await gesture.waitForFunction(() => window.__shared.values.GestureProgress === 1, undefined, { timeout: 12000 });
    const { meshes, loads } = await snapshot(gesture);
    assert.equal(loads, 1);
    assert.equal(native(meshes, route === 'chest' ? 'GestureChestHand' : 'GestureindexHand').opacity, 1);
  }
  assert.deepEqual(errors, []);
  const result = {
    originalMeshComparisons: compared, gestureFrames: samples.length, handBounds,
    maxSleeveEdgeStep, maxUpperSleeveEdgeSpan, endpointEdgeError, simultaneousAudioAndMotion: true,
    pairs: pairData, maxSameAngleDifference, maxMirrorBoundsError, palmWidthDifference,
    knuckleWidthDifference, wristSwitchPixels, fixedForearmDuringPointing: true,
    targetForearm, targetUpperArm, liftChecks, chestChecks, chestEndpointEdgeError, palmFit: fit,
  };
  await writeFile(`${target}/results.json`, JSON.stringify(result, null, 2) + '\n');
  console.log(result);
} finally {
  await browser.close();
}
