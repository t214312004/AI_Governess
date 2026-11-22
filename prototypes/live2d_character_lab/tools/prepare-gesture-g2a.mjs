import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import utils from 'playwright-core/lib/utilsBundle';

const { PNG } = utils;
const spec = JSON.parse(await readFile('design/gesture-g2a.json', 'utf8'));
const folder = 'authoring/gesture-g2a';
const sources = resolve('../../ai_voice_assistant/assets/states/layers');
await mkdir(folder, { recursive: true });
const readPng = async path => PNG.sync.read(await readFile(path));
const idle = await readPng(resolve(sources, 'idle_listen_1.png'));
const bodySource = await readPng(resolve(sources, 'speaking_1.png'));
const chinSource = await readPng(resolve(sources, 'sending_1.png'));
const originalUpper = await readPng('authoring/polish-v11/SharedSkinContinuous-hair-v11.png');
const [skinLeft, skinTop] = [753, 123];
const skins = {};
for (const pose of ['chin', 'index']) {
  skins[pose] = await readPng(`authoring/source-parts/${pose}-hand-v2.png`);
}

function contains(polygon, x, y) {
  let inside = false;
  for (let i = 0, prev = polygon.length - 1; i < polygon.length; prev = i++) {
    const [a, b] = polygon[i], [c, d] = polygon[prev];
    if ((b > y) !== (d > y) && x < (c - a) * (y - b) / (d - b) + a) inside = !inside;
  }
  return inside;
}

function getBounds(image) {
  let left = image.width, top = image.height, right = 0, bottom = 0;
  for (let y = 0; y < image.height; y++) for (let x = 0; x < image.width; x++) {
    if (!image.data[(y * image.width + x) * 4 + 3]) continue;
    left = Math.min(left, x); top = Math.min(top, y);
    right = Math.max(right, x + 1); bottom = Math.max(bottom, y + 1);
  }
  if (right <= left || bottom <= top) throw new Error('Empty part');
  return [left, top, right, bottom];
}

function polygonBounds(points) {
  return [Math.floor(Math.min(...points.map(p => p[0]))), Math.floor(Math.min(...points.map(p => p[1]))),
    Math.ceil(Math.max(...points.map(p => p[0]))), Math.ceil(Math.max(...points.map(p => p[1])))];
}

const manifest = {};
async function part(name, rect, pixelAt) {
  const [left, top, right, bottom] = rect;
  const result = new PNG({ width: right - left, height: bottom - top });
  for (let y = top; y < bottom; y++) for (let x = left; x < right; x++) {
    const pixel = pixelAt(x, y);
    if (pixel[3]) result.data.set(pixel, ((y - top) * result.width + x - left) * 4);
  }
  const [insideLeft, insideTop, insideRight, insideBottom] = getBounds(result);
  const trimmed = new PNG({width:insideRight-insideLeft,height:insideBottom-insideTop});
  PNG.bitblt(result,trimmed,insideLeft,insideTop,trimmed.width,trimmed.height,0,0);
  await writeFile(`${folder}/${name}.png`,PNG.sync.write(trimmed));
  manifest[name] = {left:left+insideLeft-spec.coordinateOrigin[0],top:top+insideTop,
    width:trimmed.width,height:trimmed.height};

}

function pixel(image, x, y) {
  const offset = (y * image.width + x) * 4;
  return image.data.subarray(offset, offset + 4);
}
function maskPixel(image, polygon, x, y) {
  let weight = 0;
  for (const ox of [.25, .75]) for (const oy of [.25, .75]) weight += Number(contains(polygon, x + ox, y + oy));
  const p = pixel(image, x, y);
  return [p[0], p[1], p[2], Math.round(p[3] * weight / 4)];
}

function palmWidth(wrist, axis, across, length, sample, sections = [.43, .5, .57]) {
  const widths = sections.map(step => {
    const center = wrist.map((value, index) => value + axis[index] * length * step);
    return [1, -1].reduce((span, direction) => {
      let distance = 0;
      for (; distance < 150; distance += .5) {
        const x = Math.round(center[0] + direction * distance * across[0]);
        const y = Math.round(center[1] + direction * distance * across[1]);
        if (sample(x, y)[3] < 128) break;
      }
      return span + distance;
    }, 0);
  });
  return widths.reduce((a, b) => a + b) / widths.length;
}

function palmMeasures(pose) {
  const { wrist, knuckles } = spec[pose].palmLandmarks;
  const dx = knuckles[0] - wrist[0], dy = knuckles[1] - wrist[1];
  const length = Math.hypot(dx, dy);
  const axis = [dx / length, dy / length];
  const across = [-axis[1], axis[0]];
  const sample = (x, y) => pixel(skins[pose], x, y);
  const width = palmWidth(wrist, axis, across, length, sample);
  const knuckleWidth = palmWidth(wrist, axis, across, length, sample, [.78, .87, .96]);
  return { wrist, axis, across, length, width, knuckleWidth };
}

const chestSource = await readPng(resolve(sources, spec.chest.source + '.png'));
const chestBounds = polygonBounds(spec.chest.handPolygon);
skins.chest = new PNG({ width: chestSource.width, height: chestSource.height });
for (let y = chestBounds[1]; y < chestBounds[3]; y++) {
  for (let x = chestBounds[0]; x < chestBounds[2]; x++) {
    const [r, g, b, alpha] = maskPixel(chestSource, spec.chest.handPolygon, x, y);
    if (b <= r + 5 || b <= g + 2) skins.chest.data.set([r, g, b, alpha], (y * chestSource.width + x) * 4);
  }
}
const sourcePalms = Object.fromEntries(['chin', 'index', 'chest'].map(pose => [pose, palmMeasures(pose)]));
const anatomy = spec.handAnthropometry;
const shoulderSpan = anatomy.shoulderMarkers[1] - anatomy.shoulderMarkers[0];
const bodyScale = shoulderSpan / anatomy.ansurShoulderBreadthMm;
// Keep both endpoints close to the drawings and enforce a shared lower
// bound from the shoulder-scaled anthropometry.
const palmTarget = {
  length: Math.max((sourcePalms.chin.length + sourcePalms.index.length) / 2,
    bodyScale * anatomy.ansurHandLengthMm * anatomy.palmLengthMm / anatomy.handLengthMm),
  width: Math.max((sourcePalms.chin.width + sourcePalms.index.width) / 2,
    bodyScale * (anatomy.ansurHandBreadthMm + anatomy.palmBreadthMm) / 2),
  knuckleWidth: (sourcePalms.chin.knuckleWidth + sourcePalms.index.knuckleWidth) / 2,
};
function fittedPalm(pose, x, y) {
  const { wrist: [wx, wy], axis: [ax, ay], across: [bx, by], length, width, knuckleWidth } = sourcePalms[pose];
  const along = (x - wx) * ax + (y - wy) * ay;
  const across = (x - wx) * bx + (y - wy) * by;
  const a = along < 0 ? along : along <= palmTarget.length
    ? along * length / palmTarget.length : along - palmTarget.length + length;
  const weight = smoothstep(-45, 23, a) * (1 - smoothstep(length + 15, length + 105, a));
  const knuckles = smoothstep(.61, .78, a / length);
  const targetKnuckles = pose === 'chest' ? knuckleWidth : palmTarget.knuckleWidth;
  const acrossScale = (palmTarget.width / width) * (1 - knuckles) + (targetKnuckles / knuckleWidth) * knuckles;
  const b = across / (1 + (acrossScale - 1) * weight);
  const sx = wx + a * ax + b * bx, sy = wy + a * ay + b * by;
  const ix = Math.floor(sx), iy = Math.floor(sy);
  const u = sx - ix, v = sy - iy;
  const raster = skins[pose];
  const top = pixel(raster, ix, iy), right = pixel(raster, ix + 1, iy);
  const bottom = pixel(raster, ix, iy + 1), diagonal = pixel(raster, ix + 1, iy + 1);
  const weights = [(1 - u) * (1 - v), u * (1 - v), (1 - u) * v, u * v];
  const samples = [top, right, bottom, diagonal];
  const alpha = samples.reduce((sum, px, index) => sum + weights[index] * px[3], 0);
  if (alpha < .5) return [0, 0, 0, 0];
  return [...[0, 1, 2].map(channel => Math.round(samples.reduce((sum, px, index) =>
    sum + weights[index] * px[3] * px[channel], 0) / alpha)), Math.round(alpha)];
}
const measuredWidths = Object.fromEntries(Object.entries(sourcePalms).map(([pose, info]) =>
  [pose, palmWidth(info.wrist, info.axis, info.across, palmTarget.length, (x, y) => fittedPalm(pose, x, y))]));
const measuredKnuckles = Object.fromEntries(Object.entries(sourcePalms).map(([pose, info]) =>
  [pose, palmWidth(info.wrist, info.axis, info.across, palmTarget.length,
    (x, y) => fittedPalm(pose, x, y), [.78, .87, .96])]));
await writeFile(`${folder}/palm-fit.json`, JSON.stringify({
  sourcePalms, palmTarget, measuredWidths, measuredKnuckles, shoulderSpan, anatomy,
}, null, 2) + '\n');

for (const pose of ['chin', 'index']) {
  const config = spec[pose];
  const source = await readPng(resolve(sources, config.source + '.png'));
  const [left, top, right, bottom] = getBounds(skins[pose]);
  const skinBounds = [left - 40, top - 40, right + 40, bottom + 7];
  const { wrist: [wx, wy], axis: [ax, ay], across: [bx, by] } = sourcePalms[pose];
  const wristDepth = (x, y) => (x - wx) * ax + (y - wy) * ay;
  // Overlap both skin meshes inside the wrist so independent keyforms cannot expose a gap.
  await part(`Gesture${pose}Hand`, skinBounds, (x, y) => {
    const [r, g, b, alpha] = fittedPalm(pose, x, y);
    return [r, g, b, Math.round(alpha * smoothstep(-55, -37, wristDepth(x, y)))];
  });
  if (pose === 'chin') {
    await part('GestureForearm', skinBounds, (x, y) => {
      const [r, g, b, alpha] = fittedPalm(pose, x, y);
      const across = (x - wx) * bx + (y - wy) * by;
      const edge = 18 * smoothstep(18, 57, -across);
      return [r, g, b, Math.round(alpha * (1 - smoothstep(-24, -13, wristDepth(x, y) + edge)))];
    });
    const opening = [...config.cuffOpening, [1031, 1044]];
    await part('GestureCuff', polygonBounds(config.sleevePolygon), (x, y) => {
      const [r, g, b, alpha] = maskPixel(source, config.sleevePolygon, x, y);
      // The source has a thin strip of the supporting hand along the elbow.
      if (y >= 1106 && r > g + 16 && r > b + 25) return [0, 0, 0, 0];
      const right = opening.findIndex(([px]) => px > x);
      if (right <= 0) return [r, g, b, alpha];
      const [x0, y0] = opening[right - 1], [x1, y1] = opening[right];
      const boundary = y0 + (y1 - y0) * (x - x0) / (x1 - x0);
      return [r, g, b, Math.round(alpha * smoothstep(boundary - 1, boundary + 1, y))];
    });
  }
}
await part('GestureSupport', polygonBounds(spec.support.polygon),
  (x, y) => maskPixel(bodySource, spec.support.polygon, x, y));
await part('GestureSupportChin', polygonBounds(spec.supportChin),
  (x, y) => maskPixel(chinSource, spec.supportChin, x, y));

const supportBounds = polygonBounds(spec.supportChin);
const chinSupport = (x, y) => maskPixel(chinSource, spec.supportChin, x, y);
await part('GestureSupportBack', supportBounds, chinSupport);
await part('GestureSupportFingers', [supportBounds[0], 1274, 842, supportBounds[3]], (x, y) => {
  const [r, g, b, a] = chinSupport(x, y);
  const weight = (1 - smoothstep(819, 841, x)) * (1 - smoothstep(1336, 1362, y));
  return [r, g, b, Math.round(a * weight)];
});

function movingBody(x, y) {
  const inRightSleeve = contains(spec.index.sleevePolygon, x + .5, y + .5);
  const raisedHand = pixel(skins.index, x, y)[3] > 0;
  const supported = contains(spec.support.polygon, x + .5, y + .5);
  if ((inRightSleeve || raisedHand) && !supported) {
    // Avoid repeating one row of the idle sleeve under the bending elbow.
    return y < 1262 ? pixel(idle, x, Math.min(y, 1210)) : pixel(bodySource, x, y);
  }
  const [from, to] = spec.body.upperJoin;
  const blend = smoothstep(from, to, y);
  const a = pixel(idle, x, y), b = pixel(bodySource, x, y);
  return Array.from(b, (v, channel) => Math.round(a[channel] + blend * (v - a[channel])));
}

const upperSleeveRect = [745, 770, 930, 1262];
function oldElbow(x, y) {
  return y >= upperSleeveRect[3] && y < 1390 &&
    (contains(spec.index.sleevePolygon, x + .5, y + .5) ||
      (x < 965 && contains(spec.support.polygon, x + .5, y + .5)));
}

await part('GestureElbowUnderlay', [745, 1262, 965, 1390],
  (x, y) => oldElbow(x, y) ? movingBody(x, y) : [0, 0, 0, 0]);
await part(spec.body.id, spec.body.rect, (x, y) => {
  const separateSleeve = x < upperSleeveRect[2] && y >= upperSleeveRect[1] && y < upperSleeveRect[3];
  return separateSleeve || oldElbow(x, y) ? [0, 0, 0, 0] : movingBody(x, y);
});

function smoothstep(start, end, value) {
  const t = Math.max(0, Math.min(1, (value - start) / (end - start)));
  return t * t * (3 - 2 * t);
}

// The two original outlines run around x=768 and x=781 below the shoulder.
// Keep a common mesh between them, with an almost straight middle section.
function sleeveEdge(y) {
  const shoulder = 821 - .52 * (y - 760);
  const join = smoothstep(788, 901, y);
  return shoulder + (774 - shoulder) * join + 7 * smoothstep(1172, 1262, y);
}

function originalSleeve(x, y) {
  if (y >= 1024) return pixel(idle, x, Math.min(y, 1196));
  return x < skinLeft ? [0, 0, 0, 0] : pixel(originalUpper, x - skinLeft, y - skinTop);
}

const sleeveOffsets = Array.from({ length: upperSleeveRect[3] - upperSleeveRect[1] }, (_, index) => {
  const y = upperSleeveRect[1] + index;
  let x = upperSleeveRect[0];
  while (x < 875 && originalSleeve(x, y)[3] < 128) x++;
  return sleeveEdge(y) - x;
});
await part('GestureUpperSleeve', upperSleeveRect, (x, y) => {
  const contour = sleeveEdge(y);
  const blend = 1 - smoothstep(825, 925, x);
  const shift = sleeveOffsets[y - upperSleeveRect[1]] * blend;
  const sample = x - shift;
  const left = Math.floor(sample);
  const a = originalSleeve(left, y);
  const b = originalSleeve(left + 1, y);
  const weight = sample - left;
  const opacity = smoothstep(773, 823, y) * (1 - smoothstep(1246, 1262, y));
  const rightJoin = 1 - (1 - smoothstep(987, 1024, y)) * smoothstep(874, 930, x);
  const rgb = Array.from(a, (v, channel) =>
    Math.round((v + (b[channel] - v) * weight) * (channel === 3 ? opacity * rightJoin : 1)));
  if (x > contour + 4) return rgb;
  const coverage = Math.max(0, Math.min(1, x + .5 - contour));
  const inside = smoothstep(1, 3.5, x - contour);
  const ink = [31, 41, 52];
  return [...ink.map((value, channel) => Math.round(value + (rgb[channel] - value) * inside)),
    Math.round(coverage * opacity * 255)];
});

// Bare fabric behind the active elbow. The original underlay contains a
// painted elbow and a hand, which cannot follow the rotating front sleeve.
await part('GestureChestSleeveBridge', [750, 1180, 943, 1336], (x, y) => {
  const contour = sleeveEdge(y);
  const sampleY = Math.min(y, 1196);
  const slice = Math.min(sampleY, upperSleeveRect[3] - 1) - upperSleeveRect[1];
  const xOffset = sleeveOffsets[slice] * (1 - smoothstep(825, 925, x));
  const [r, g, b, a] = originalSleeve(Math.round(x - xOffset), sampleY);
  const coverage = Math.max(0, Math.min(1, x + .5 - contour));
  const opacity = smoothstep(1180, 1252, y) * (1 - smoothstep(1293, 1335, y)) *
    (1 - smoothstep(918, 942, x));
  return [r, g, b, Math.round(a * coverage * opacity)];
});

const mirrorX = 2 * spec.mirrorAxis;
await part('GesturePassiveShoulder', [1346, 774, 1480, 1024], (x, y) => {
  const [r, g, b, a] = pixel(originalUpper, x - skinLeft, y - skinTop);
  return [r, g, b, Math.round(a * smoothstep(1346, 1358, x) * smoothstep(774, 784, y))];
});

const { wrist: chestWrist, axis: chestAxis } = sourcePalms.chest;
await part('GestureChestHand', [chestBounds[0] - 40, chestBounds[1] - 44, chestBounds[2] + 40, chestBounds[3]],
  (x, y) => {
    const [r, g, b, alpha] = fittedPalm('chest', x, y);
    const depth = (x - chestWrist[0]) * chestAxis[0] + (y - chestWrist[1]) * chestAxis[1];
    return [r, g, b, Math.round(alpha * smoothstep(-51, -30, depth))];
  });

// Clear the old shoulder edges only in the gesture copy of the v11 artwork.
// The continuous sleeve above supplies the same region in the new pose.
for (let y = 0; y < originalUpper.height; y++) {
  const vertical = smoothstep(784, 832, y + skinTop);
  if (!vertical) continue;
  for (let x = 0; x < originalUpper.width; x++) {
    const canonical = Math.min(x + skinLeft, mirrorX - x - skinLeft - 1);
    if (canonical >= 874) continue;
    const coverage = vertical * (1 - smoothstep(822, 874, canonical));
    const alpha = (y * originalUpper.width + x) * 4 + 3;
    originalUpper.data[alpha] = Math.round(originalUpper.data[alpha] * (1 - coverage));
  }
}
await writeFile(`${folder}/SharedSkinGesture.png`, PNG.sync.write(originalUpper));

const axis = spec.mirrorAxis - spec.coordinateOrigin[0];
for (const [name, rect] of Object.entries(manifest)) {
  const source = await readPng(`${folder}/${name}.png`);
  const mirrored = new PNG({ width: source.width, height: source.height });
  for (let y = 0; y < source.height; y++) for (let x = 0; x < source.width; x++) {
    const start = (y * source.width + x) * 4;
    const target = (y * source.width + source.width - 1 - x) * 4;
    mirrored.data.set(source.data.subarray(start, start + 4), target);
  }
  await writeFile(`${folder}/${name}Left.png`, PNG.sync.write(mirrored));
  manifest[`${name}Left`] = { ...rect, left: 2 * axis - rect.left - rect.width };
}

await writeFile(`${folder}/parts.json`, JSON.stringify(manifest, null, 2) + '\n');
console.log('Prepared layered arms and mirrored them around the centerline.', palmTarget);
