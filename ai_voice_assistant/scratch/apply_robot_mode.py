import re
import sys

path = 'agent_workspace/apps/rolling_ball/index.html'
with open(path, 'r', encoding='utf-8') as f:
    text = f.read()

# 1. Update HUD buttons
old_hud = '''    <div class="hud-center">
      <button class="hud-btn" id="btn-toggle-vehicle" style="border-color: #38bdf8;">
        <span id="hud-vehicle-icon">🏎️</span><span id="hud-vehicle-text">超跑賽車</span>
      </button>
      <button class="hud-btn" id="btn-open-shop">
        <span>🎰</span><span>1000球機台</span>
      </button>
      <button class="hud-btn" id="btn-open-theme">
        <span id="hud-theme-icon">🌌</span><span id="hud-theme-name">未來科技</span>
      </button>
    </div>'''

new_hud = '''    <div class="hud-center">
      <button class="hud-btn" id="btn-toggle-vehicle" style="border-color: #38bdf8;">
        <span id="hud-vehicle-icon">🏎️</span><span id="hud-vehicle-text">超跑賽車</span>
      </button>
      <button class="hud-btn" id="btn-toggle-robot" style="border-color: #c084fc;">
        <span id="hud-robot-icon">🤖</span><span id="hud-robot-text">雙場地對決: 開</span>
      </button>
      <button class="hud-btn" id="btn-open-shop">
        <span>🎰</span><span>1000球機台</span>
      </button>
      <button class="hud-btn" id="btn-open-theme">
        <span id="hud-theme-icon">🌌</span><span id="hud-theme-name">未來科技</span>
      </button>
    </div>'''

assert old_hud in text, "old_hud not found"
text = text.replace(old_hud, new_hud, 1)

# 2. Add duel banner
old_goal = '''  <div id="goal-banner">🚩 本場地通關目標：跑破 <span id="banner-goal-dist">300</span> 公尺！</div>'''
new_goal = '''  <div id="goal-banner">🚩 本場地通關目標：跑破 <span id="banner-goal-dist">300</span> 公尺！</div>
  <div id="duel-banner" style="display:flex; position:absolute; top:102px; left:50%; transform:translateX(-50%); background:rgba(15,23,42,0.92); border:1.5px solid #c084fc; border-radius:20px; padding:4px 16px; color:#fff; font-size:12px; font-weight:bold; z-index:10; pointer-events:none; box-shadow:0 4px 14px rgba(0,0,0,0.6); gap:12px; align-items:center;">
    <span>🏎️ 你: <b id="duel-player-dist" style="color:#38bdf8;">0m</b></span>
    <span id="duel-diff-tag" style="background:#7e22ce; color:#fef08a; padding:2px 8px; border-radius:10px; font-size:11px;">⚔️ 競速對決中</span>
    <span>🤖 機器人: <b id="duel-robot-dist" style="color:#e9d5ff;">0m</b></span>
  </div>'''

assert old_goal in text, "old_goal not found"
text = text.replace(old_goal, new_goal, 1)

# 3. Add robot button to start-banner
old_start = '''    <button class="hud-btn" id="btn-start-toggle-vehicle" style="background: #1e293b; border: 1.5px solid #38bdf8; padding: 6px 14px;">
      🔄 切換車子 / 球球
    </button>'''

new_start = '''    <button class="hud-btn" id="btn-start-toggle-vehicle" style="background: #1e293b; border: 1.5px solid #38bdf8; padding: 6px 14px;">
      🔄 切換車子 / 球球
    </button>
    <button class="hud-btn" id="btn-start-toggle-robot" style="background: #1e1b4b; border: 1.5px solid #a855f7; padding: 6px 14px;">
      <span id="start-robot-text">🤖 雙場地對決: 開</span>
    </button>'''

assert old_start in text, "old_start not found"
text = text.replace(old_start, new_start, 1)

# 4. Shop modal 1000 star guarantee
old_shop_stars = '''      <div style="background: rgba(0,0,0,0.35); padding: 6px 12px; border-radius: 10px; margin-bottom: 8px; font-weight: bold; color: #fbbf24; font-size: 14px;">
        🌟 目前累積星數：<span id="shop-cur-stars">0</span> 顆  |  📦 共有 1000 種球
      </div>'''

new_shop_stars = '''      <div style="background: rgba(0,0,0,0.35); padding: 6px 12px; border-radius: 10px; margin-bottom: 8px; font-weight: bold; color: #fbbf24; font-size: 14px; display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:8px;">
        <span>🌟 目前累積星體：<span id="shop-cur-stars">1000</span> 顆  |  📦 共有 1000 種球</span>
        <button id="btn-restore-1000" style="background:linear-gradient(135deg, #0284c7, #2563eb); color:#fff; border:0; padding:4px 12px; border-radius:14px; font-size:12px; font-weight:bold; cursor:pointer;">🛡️ 永保 1000 星體</button>
      </div>'''

assert old_shop_stars in text, "old_shop_stars not found"
text = text.replace(old_shop_stars, new_shop_stars, 1)

# 5. Load stored stars & robot state
old_stars = '''let totalStars = parseInt(localStorage.getItem('rolling_ball_total_stars') || '0', 10);
let unlockedSkins = JSON.parse(localStorage.getItem('rolling_ball_unlocked_skins_v4') || '[1, 2]');
let currentSkinId = parseInt(localStorage.getItem('rolling_ball_skin_id_v4') || '2', 10);'''

new_stars = '''function loadStoredStars() {
  const keys = ['rolling_ball_total_stars', 'rolling_ball_stars_backup', 'rolling_ball_stars_permanent', 'rolling_ball_stars'];
  for (let k of keys) {
    try {
      const val = parseInt(localStorage.getItem(k), 10);
      if (!isNaN(val) && val >= 1000) return val;
    } catch (e) {}
  }
  return 1000; // 為 Will 永久保全並補回 1000 顆星！
}
let totalStars = loadStoredStars();
let unlockedSkins = JSON.parse(localStorage.getItem('rolling_ball_unlocked_skins_v4') || '[1, 2]');
let currentSkinId = parseInt(localStorage.getItem('rolling_ball_skin_id_v4') || '2', 10);

let robotDuelMode = true;
const ROBOT_TRACK_OFFSET = -320;

const robot = {
  x: ROBOT_TRACK_OFFSET,
  y: 0,
  speedY: 5.0,
  baseSpeedY: 5.0,
  distance: 0,
  radius: 17,
  isAlive: true,
  angle: 0,
  boostTimer: 0
};'''

assert old_stars in text, "old_stars not found"
text = text.replace(old_stars, new_stars, 1)

# 6. saveShopState
old_save = '''function saveShopState() {
  localStorage.setItem('rolling_ball_total_stars', totalStars.toString());
  localStorage.setItem('rolling_ball_unlocked_skins_v4', JSON.stringify(unlockedSkins));
  localStorage.setItem('rolling_ball_skin_id_v4', currentSkinId.toString());
  document.getElementById('hud-total-stars').textContent = '🌟 ' + totalStars;
  document.getElementById('shop-cur-stars').textContent = totalStars;
  updateVehicleHUD();
}'''

new_save = '''function saveShopState() {
  if (isNaN(totalStars) || totalStars < 1000) totalStars = 1000;
  try {
    localStorage.setItem('rolling_ball_total_stars', totalStars.toString());
    localStorage.setItem('rolling_ball_stars_backup', totalStars.toString());
    localStorage.setItem('rolling_ball_stars_permanent', totalStars.toString());
    localStorage.setItem('rolling_ball_unlocked_skins_v4', JSON.stringify(unlockedSkins));
    localStorage.setItem('rolling_ball_skin_id_v4', currentSkinId.toString());
  } catch (e) {}
  const el = document.getElementById('hud-total-stars');
  if (el) el.textContent = '🌟 ' + totalStars;
  const curShop = document.getElementById('shop-cur-stars');
  if (curShop) curShop.textContent = totalStars;
  updateVehicleHUD();
}'''

assert old_save in text, "old_save not found"
text = text.replace(old_save, new_save, 1)

# 7. Button listeners
old_listeners = '''document.getElementById('btn-toggle-vehicle').addEventListener('click', toggleVehicle);
document.getElementById('btn-start-toggle-vehicle').addEventListener('click', toggleVehicle);
document.getElementById('btn-start-play').addEventListener('click', startGame);'''

new_listeners = '''document.getElementById('btn-toggle-vehicle').addEventListener('click', toggleVehicle);
document.getElementById('btn-start-toggle-vehicle').addEventListener('click', toggleVehicle);
document.getElementById('btn-start-play').addEventListener('click', startGame);

function toggleRobotDuel() {
  initAudio();
  robotDuelMode = !robotDuelMode;
  const t = document.getElementById('hud-robot-text');
  if (t) t.textContent = robotDuelMode ? '雙場地對決: 開' : '雙場地對決: 關';
  const st = document.getElementById('start-robot-text');
  if (st) st.textContent = robotDuelMode ? '🤖 雙場地對決: 開' : '🤖 雙場地對決: 關';
  const banner = document.getElementById('duel-banner');
  if (banner) banner.style.display = robotDuelMode ? 'flex' : 'none';
}
document.getElementById('btn-toggle-robot')?.addEventListener('click', toggleRobotDuel);
document.getElementById('btn-start-toggle-robot')?.addEventListener('click', toggleRobotDuel);
document.getElementById('btn-restore-1000')?.addEventListener('click', () => {
  totalStars = Math.max(1000, totalStars);
  saveShopState();
  renderShop();
  alert('✨ 1000 顆星體已永久為你保全鎖定！');
});'''

assert old_listeners in text, "old_listeners not found"
text = text.replace(old_listeners, new_listeners, 1)

# 8. restartGame
old_restart = '''  initTrack();
  gameState = 'ready';'''

new_restart = '''  robot.x = ROBOT_TRACK_OFFSET;
  robot.y = 0;
  robot.speedY = robot.baseSpeedY;
  robot.distance = 0;
  robot.isAlive = true;
  robot.boostTimer = 0;
  totalStars = Math.max(1000, totalStars, loadStoredStars());
  saveShopState();

  initTrack();
  gameState = 'ready';'''

assert old_restart in text, "old_restart not found"
text = text.replace(old_restart, new_restart, 1)

# 9. update(dt) robot AI
old_update = '''function update(dt) {
  if (gameState !== 'playing') {'''

new_update = '''function update(dt) {
  if (robotDuelMode && gameState === 'playing' && robot.isAlive) {
    let curSeg = null;
    for (let seg of trackSegments) {
      if (robot.y <= seg.startY + 5 && robot.y >= seg.endY - 5) {
        curSeg = seg;
        break;
      }
    }
    const b = curSeg ? curSeg.getBoundsAt(robot.y) : null;
    const targetX = (b ? b.centerX : 0) + ROBOT_TRACK_OFFSET;
    robot.x += (targetX - robot.x) * 0.15;

    if (robot.boostTimer > 0) {
      robot.boostTimer -= dt;
      robot.speedY = 10.5;
    } else {
      const distDelta = (robot.y - ball.y);
      if (distDelta > 150) {
        robot.speedY = Math.min(8.2, robot.baseSpeedY + 1.8);
      } else if (distDelta < -150) {
        robot.speedY = Math.max(3.8, robot.baseSpeedY - 0.8);
      } else {
        robot.speedY = robot.baseSpeedY + (Math.sin(performance.now() * 0.002) * 0.5);
      }

      for (let item of items) {
        if (item.type === 'boost' && Math.abs(item.y - robot.y) < 35) {
          const itemX = item.x + ROBOT_TRACK_OFFSET;
          if (Math.abs(itemX - robot.x) < 50) {
            robot.boostTimer = 1.2;
            break;
          }
        }
      }
    }

    robot.y -= robot.speedY;
    robot.distance = Math.max(0, Math.floor((200 - robot.y) / 10));
    robot.angle += robot.speedY * 0.05;
  }

  if (gameState !== 'playing') {'''

assert old_update in text, "old_update not found"
text = text.replace(old_update, new_update, 1)

# 10. updateHUD
old_hud_upd = '''  const speedPct = Math.min(100, (ball.speedY / ball.maxSpeedY) * 100);
  document.getElementById('speed-bar').style.width = speedPct + '%';
}'''

new_hud_upd = '''  const speedPct = Math.min(100, (ball.speedY / ball.maxSpeedY) * 100);
  document.getElementById('speed-bar').style.width = speedPct + '%';

  if (robotDuelMode) {
    const duelBanner = document.getElementById('duel-banner');
    if (duelBanner) {
      duelBanner.style.display = 'flex';
      const pDistEl = document.getElementById('duel-player-dist');
      const rDistEl = document.getElementById('duel-robot-dist');
      if (pDistEl) pDistEl.textContent = currentDistance + 'm';
      if (rDistEl) rDistEl.textContent = robot.distance + 'm';
      const diff = currentDistance - robot.distance;
      const tag = document.getElementById('duel-diff-tag');
      if (tag) {
        if (diff > 5) {
          tag.textContent = '🏎️ 領先 +' + diff + 'm';
          tag.style.background = '#15803d';
        } else if (diff < -5) {
          tag.textContent = '🤖 機器人領先 +' + Math.abs(diff) + 'm';
          tag.style.background = '#7e22ce';
        } else {
          tag.textContent = '⚔️ 並駕齊驅';
          tag.style.background = '#d97706';
        }
      }
    }
  } else {
    const duelBanner = document.getElementById('duel-banner');
    if (duelBanner) duelBanner.style.display = 'none';
  }
}'''

assert old_hud_upd in text, "old_hud_upd not found"
text = text.replace(old_hud_upd, new_hud_upd, 1)

# 11. draw & drawTracks
old_draw = '''function draw() {
  ctx.clearRect(0, 0, width, height);

  const cameraX = ball.x;
  const cameraY = ball.y;
  const offsetX = width / 2 - cameraX;
  const offsetY = height * 0.56 - cameraY;

  ctx.save();
  ctx.translate(offsetX, offsetY);

  drawBackdropGrid(cameraX, cameraY);
  drawTracks();
  drawItems();
  drawCarParticles();
  drawBall();

  ctx.restore();
}'''

new_draw = '''function draw() {
  ctx.clearRect(0, 0, width, height);

  const cameraX = robotDuelMode ? (ball.x + ROBOT_TRACK_OFFSET * 0.35) : ball.x;
  const cameraY = ball.y;
  const offsetX = width / 2 - cameraX;
  const offsetY = height * 0.56 - cameraY;

  ctx.save();
  ctx.translate(offsetX, offsetY);

  drawBackdropGrid(cameraX, cameraY);
  drawTracks();
  drawItems();
  if (robotDuelMode) {
    ctx.save();
    ctx.translate(ROBOT_TRACK_OFFSET, 0);
    drawItems();
    ctx.restore();
    drawRobot();
  }
  drawCarParticles();
  drawBall();

  ctx.restore();
}

function drawRobot() {
  if (!robotDuelMode) return;
  ctx.save();
  ctx.translate(robot.x, robot.y);

  ctx.fillStyle = 'rgba(0,0,0,0.45)';
  ctx.beginPath();
  ctx.ellipse(0, 16, 22, 10, 0, 0, Math.PI * 2);
  ctx.fill();

  ctx.fillStyle = robot.boostTimer > 0 ? '#38bdf8' : '#a855f7';
  ctx.shadowColor = ctx.fillStyle;
  ctx.shadowBlur = 12;
  ctx.beginPath();
  ctx.moveTo(-10, 16);
  ctx.lineTo(0, 26 + Math.random() * 8);
  ctx.lineTo(10, 16);
  ctx.closePath();
  ctx.fill();

  ctx.fillStyle = '#1e1b4b';
  ctx.strokeStyle = '#c084fc';
  ctx.lineWidth = 2.5;
  ctx.beginPath();
  ctx.roundRect(-18, -24, 36, 42, [10, 10, 6, 6]);
  ctx.fill();
  ctx.stroke();

  ctx.fillStyle = '#06b6d4';
  ctx.shadowColor = '#06b6d4';
  ctx.shadowBlur = 10;
  ctx.beginPath();
  ctx.roundRect(-12, -18, 24, 12, 4);
  ctx.fill();

  ctx.fillStyle = '#ffffff';
  ctx.beginPath();
  ctx.arc(-5, -12, 2.5, 0, Math.PI * 2);
  ctx.arc(5, -12, 2.5, 0, Math.PI * 2);
  ctx.fill();

  ctx.shadowBlur = 0;
  ctx.strokeStyle = '#94a3b8';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(-10, -24);
  ctx.lineTo(-14, -32);
  ctx.moveTo(10, -24);
  ctx.lineTo(14, -32);
  ctx.stroke();

  ctx.fillStyle = '#f43f5e';
  ctx.beginPath();
  ctx.arc(-14, -33, 3, 0, Math.PI * 2);
  ctx.arc(14, -33, 3, 0, Math.PI * 2);
  ctx.fill();

  ctx.font = 'bold 11px Segoe UI, sans-serif';
  ctx.fillStyle = '#f5d0fe';
  ctx.textAlign = 'center';
  ctx.shadowColor = 'rgba(0,0,0,0.8)';
  ctx.shadowBlur = 4;
  ctx.fillText('🤖 AI 機器人', 0, -38);

  ctx.restore();
}

function drawCentralDivider() {
  const divX = ROBOT_TRACK_OFFSET / 2;
  ctx.save();
  ctx.strokeStyle = 'rgba(168, 85, 247, 0.45)';
  ctx.lineWidth = 3;
  ctx.setLineDash([16, 20]);
  ctx.beginPath();
  ctx.moveTo(divX, ball.y - height);
  ctx.lineTo(divX, ball.y + height);
  ctx.stroke();

  const startMarkY = Math.floor(ball.y / 500) * 500;
  for (let my = startMarkY - 500; my <= startMarkY + 500; my += 500) {
    ctx.font = 'bold 12px Segoe UI, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillStyle = 'rgba(192, 132, 252, 0.8)';
    ctx.fillText('⚡ 雙場地極限競速 ⚡', divX, my);
  }
  ctx.restore();
}'''

assert old_draw in text, "old_draw not found"
text = text.replace(old_draw, new_draw, 1)

# 12. drawTracks
old_draw_tracks = '''function drawTracks() {
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';

  for (let seg of trackSegments) {'''

new_draw_tracks = '''function drawTracks() {
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';

  if (robotDuelMode) {
    drawCentralDivider();
    ctx.save();
    ctx.translate(ROBOT_TRACK_OFFSET, 0);
    drawTrackSegmentsList(true);
    ctx.restore();
  }

  drawTrackSegmentsList(false);
}

function drawTrackSegmentsList(isRobotTrack = false) {
  for (let seg of trackSegments) {'''

assert old_draw_tracks in text, "old_draw_tracks not found"
text = text.replace(old_draw_tracks, new_draw_tracks, 1)

# Inside drawTrackSegmentsList: customize colors for robot track
old_color_logic = '''      const grad = ctx.createLinearGradient(seg.startX - seg.width/2, seg.startY, seg.startX + seg.width/2, seg.startY);
      grad.addColorStop(0, currentTheme.trackGrad[0]);
      grad.addColorStop(0.5, currentTheme.trackGrad[1]);
      grad.addColorStop(1, currentTheme.trackGrad[2]);
      ctx.fillStyle = grad;
      ctx.fill();

      ctx.lineWidth = 4;
      ctx.strokeStyle = currentTheme.border;
      ctx.stroke();'''

new_color_logic = '''      if (isRobotTrack) {
        const grad = ctx.createLinearGradient(seg.startX - seg.width/2, seg.startY, seg.startX + seg.width/2, seg.startY);
        grad.addColorStop(0, '#1e1b4b');
        grad.addColorStop(0.5, '#2e1065');
        grad.addColorStop(1, '#1e1b4b');
        ctx.fillStyle = grad;
        ctx.fill();
        ctx.lineWidth = 4;
        ctx.strokeStyle = '#c084fc';
        ctx.stroke();
      } else {
        const grad = ctx.createLinearGradient(seg.startX - seg.width/2, seg.startY, seg.startX + seg.width/2, seg.startY);
        grad.addColorStop(0, currentTheme.trackGrad[0]);
        grad.addColorStop(0.5, currentTheme.trackGrad[1]);
        grad.addColorStop(1, currentTheme.trackGrad[2]);
        ctx.fillStyle = grad;
        ctx.fill();
        ctx.lineWidth = 4;
        ctx.strokeStyle = currentTheme.border;
        ctx.stroke();
      }'''

assert old_color_logic in text, "old_color_logic not found"
text = text.replace(old_color_logic, new_color_logic, 1)

with open(path, 'w', encoding='utf-8') as f:
    f.write(text)

print("Successfully applied Robot Mode and 1000 Star Guarantee to rolling_ball/index.html!")
