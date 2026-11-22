import art from '../design/gesture-g2a.json';

function ease(value: number) {
  const t = Math.max(0, Math.min(1, value));
  return t * t * (3 - 2 * t);
}

const angle = ([x, y]: number[], [elbowX, elbowY]: number[]) => Math.atan2(y - elbowY, x - elbowX);
const elbow = art.chin.elbow;
const lowerAngle = angle(art.inbetween.targetWrist, elbow);
const neutralAngle = angle(art.chin.wrist, elbow);
const pointAngle = angle(art.index.wrist, art.index.elbow);
const returnArc = neutralAngle - lowerAngle;
const pointingArc = pointAngle - neutralAngle;
const timing = art.motion;
const liftAngle = -timing.lift.startDegrees * Math.PI / 180;
const liftReach = (liftAngle - lowerAngle) / returnArc;
const chest = art.chest.motion;

export type GestureTarget = 'point' | 'chest';

/** Share the low arc, then use the elbow-centered pointing arc from 45 degrees. */
export function gestureG2a(progress: number, flex: number, side = 0, target: GestureTarget = 'point') {
  const toChest = target === 'chest';
  const liftProgress = ease((progress - timing.raiseStart) / (timing.raiseEnd - timing.raiseStart));
  const raised = (pointAngle - lowerAngle) *
    liftProgress;
  const reach = progress < timing.raiseStart
    ? 1 - ease(progress / timing.lowerEnd)
    : raised >= returnArc ? raised / returnArc : 1 + (raised - returnArc) / pointingArc;
  const pointing = ease((progress - timing.pointStart) / timing.pointBlend);
  const extension = ease((progress - .893) / .059);
  const lift = (lowerAngle + raised - liftAngle) / (pointAngle - liftAngle);
  const poseReach = progress < timing.raiseStart ? reach
    : toChest ? chest.keyStart + liftProgress
    : lift > 0 ? timing.lift.keyStart + Math.min(1, lift) : reach;
  const chinFit = progress < timing.raiseStart ? Math.max(0, (reach - liftReach) / (1 - liftReach)) : 0;
  const grip = toChest ? chinFit - liftProgress : chinFit;
  return {
    ParamGestureReach: poseReach,
    ParamGestureVariant: toChest ? (progress >= chest.palmStart ? -1 : 0) : pointing,
    ParamGestureChestFold: toChest ? chest.foldAmount * (1 - ease((progress - chest.palmStart) / chest.unfoldSpan)) : 0,
    ParamGestureIndexFlex: toChest ? 0 : Math.max(flex, 1 - extension),
    ParamGestureBodyFit: toChest ? -1 - liftProgress * (1 - .75 * liftProgress) : 2 * ease(reach - 1) - 1,
    ParamGestureChinSupport: toChest ? chinFit - .55 * liftProgress : chinFit,
    ParamGestureContact: toChest ? grip : 1 - ease((reach - .34) / .31),
    ParamGestureSupportSettle: toChest ? -1 : ease((progress - timing.pointStart) / .068),
    ParamGestureSide: side,
  };
}
