export const STATES = {
  IDLE_LISTEN: { label: '待機聆聽', angle: 0, tilt: 0, brow: 0, smile: 0.15, pose: '原始雙手交疊；待修正拆件遮擋' },
  COLLECTING: { label: '收音中', angle: -5, tilt: -3, brow: 0.25, smile: 0, pose: '手靠耳旁：待補件與綁定' },
  SENDING: { label: '思考中', angle: 5, tilt: 4, brow: -0.15, smile: -0.1, pose: '手指托下巴：待補件與綁定' },
  SPEAKING: { label: '說話中', angle: 0, tilt: 1, brow: 0.1, smile: 0.3, pose: '抬指／手放胸前／攤掌：待補件與綁定' },
  HOT_LISTEN: { label: '等待回覆', angle: 0, tilt: -2, brow: 0.25, smile: 0.15, pose: '胸前合手：待補件與綁定' },
};
export class StateController {
  state = 'IDLE_LISTEN';
  current = { angle: 0, tilt: 0, brow: 0, smile: 0.15 };
  set(state) { if (!STATES[state]) throw new Error(`Unknown state: ${state}`); this.state = state; }
  tick(dt) {
    const alpha = 1 - Math.exp(-Math.max(0, Math.min(dt, 0.1)) / 0.22);
    for (const key of Object.keys(this.current)) this.current[key] += (STATES[this.state][key] - this.current[key]) * alpha;
    return this.current;
  }
}
export function rmsToMouth(samples, volume = 1) {
  if (!samples.length || volume <= 0) return 0;
  const rms = Math.sqrt(samples.reduce((sum, x) => sum + x * x, 0) / samples.length) * volume;
  return Math.min(1, Math.max(0, (rms - 0.012) * 8));
}
export function approachMouth(current, target, dt) {
  return current + (target - current) * (1 - Math.exp(-Math.max(0, dt) / (target > current ? 0.035 : 0.08)));
}
