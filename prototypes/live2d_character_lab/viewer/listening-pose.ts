type Key = readonly [number, number];
const duration = 12;
function sample(keys: readonly Key[], time: number) {
  for (let i = 1; i < keys.length; i++) {
    const [end, to] = keys[i];
    if (time <= end) {
      const [start, from] = keys[i - 1];
      const t = (time - start) / (end - start);
      return from + (to - from) * t * t * (3 - 2 * t);
    }
  }
  return keys[keys.length - 1][1];
}
const gaze: Key[] = [[0,0],[1.1,0],[1.29,-.38],[3.85,-.38],[4.1,.28],[7.7,.28],[7.9,.1],[9.6,.1],[9.85,0],[12,0]];
const yaw: Key[] = [[0,0],[1.32,0],[2.21,-2.7],[4.17,-2.7],[5.18,2.2],[8,2.2],[9,.8],[10,.8],[11.2,0],[12,0]];
const pitch: Key[] = [[0,0],[5.65,0],[6.05,-1.65],[6.74,.3],[7.35,0],[12,0]];
const roll: Key[] = [[0,0],[1.7,0],[2.8,-1.3],[4.5,-1.3],[5.8,.85],[9,.85],[10.8,0],[12,0]];
const blink: Key[] = [[0,1],[.085,0],[.115,0],[.28,1]];
export function listeningPose(seconds: number) {
  const time = seconds % duration;
  const blinkStart = [2.94, 7.52, 10.91].find(start => time >= start && time <= start + .28);
  const open = blinkStart === undefined ? 1 : sample(blink,time-blinkStart);
  return {ParamEyeBallX:sample(gaze,time),ParamAngleX:sample(yaw,time),
    ParamAngleY:sample(pitch,time),ParamHeadTilt:sample(roll,time),
    ParamEyeROpen:open,ParamEyeLOpen:open};
}
