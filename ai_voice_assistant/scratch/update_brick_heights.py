path = 'agent_workspace/apps/lego_tower/index.html'
with open(path, 'r', encoding='utf-8') as f:
    text = f.read()

# Update buttons
old_btn = '''    <div class="controls-row">
      <button class="btn-brick active" data-type="1x1">
        <span style="font-size:16px;">🟥</span>
        <span>1顆凸粒</span>
      </button>
      <button class="btn-brick" data-type="1x2">
        <span style="font-size:16px;">🟦</span>
        <span>2顆凸粒</span>
      </button>
      <button class="btn-brick" data-type="1x3">
        <span style="font-size:16px;">🟩</span>
        <span>3顆凸粒</span>
      </button>
      <button class="btn-brick" data-type="1x4">
        <span style="font-size:16px;">🟨</span>
        <span>4顆長條</span>
      </button>
      <button class="btn-brick" data-type="2x2">
        <span style="font-size:16px;">🟪</span>
        <span>2x2方塊</span>
      </button>
    </div>'''

new_btn = '''    <div class="controls-row">
      <button class="btn-brick" data-type="plate_1x2">
        <span style="font-size:16px;">🥞</span>
        <span>扁平薄片</span>
      </button>
      <button class="btn-brick" data-type="plate_1x4">
        <span style="font-size:16px;">🛹</span>
        <span>長扁底板</span>
      </button>
      <button class="btn-brick active" data-type="std_1x2">
        <span style="font-size:16px;">🧱</span>
        <span>標準高磚</span>
      </button>
      <button class="btn-brick" data-type="std_1x4">
        <span style="font-size:16px;">🟨</span>
        <span>長條高磚</span>
      </button>
      <button class="btn-brick" data-type="tall_2x2">
        <span style="font-size:16px;">🗼</span>
        <span>特高厚磚</span>
      </button>
    </div>'''

assert old_btn in text, "old_btn not found"
text = text.replace(old_btn, new_btn, 1)

# Update BRICK_SHAPES
old_shapes = '''const BRICK_SHAPES = [
  { type: '1x1', width: 36, height: 28, studs: 1, name: '1顆凸粒方塊' },
  { type: '1x2', width: 68, height: 28, studs: 2, name: '2顆凸粒長塊' },
  { type: '1x3', width: 100, height: 28, studs: 3, name: '3顆凸粒樑柱' },
  { type: '1x4', width: 132, height: 28, studs: 4, name: '4顆凸粒長條' },
  { type: '2x2', width: 68, height: 38, studs: 4, name: '2x2厚實方塊' }
];'''

new_shapes = '''const BRICK_SHAPES = [
  { type: 'plate_1x2', width: 68, height: 14, studs: 2, name: '2顆扁平薄片 (🥞 扁)', heightType: '扁片 (14mm)' },
  { type: 'plate_1x4', width: 132, height: 14, studs: 4, name: '4顆長扁底板 (🥞 扁)', heightType: '長扁板 (14mm)' },
  { type: 'std_1x2', width: 68, height: 28, studs: 2, name: '2顆標準高磚 (🧱 標準)', heightType: '標準高 (28mm)' },
  { type: 'std_1x4', width: 132, height: 28, studs: 4, name: '4顆長條高磚 (🧱 標準)', heightType: '標準高 (28mm)' },
  { type: 'tall_2x2', width: 72, height: 44, studs: 4, name: '2x2超高厚磚 (🗼 特高)', heightType: '雙倍特高 (44mm)' }
];'''

assert old_shapes in text, "old_shapes not found"
text = text.replace(old_shapes, new_shapes, 1)

# Update catalog item meta
old_meta = '''    card.innerHTML = `
      <div style="width:36px; height:20px; background:${brick.color}; border:1px solid rgba(0,0,0,0.3); border-radius:4px; box-shadow:0 2px 4px rgba(0,0,0,0.3);"></div>
      <div class="card-name">${brick.name}</div>
      <div class="card-meta">${brick.studs} 顆凸粒 · ${brick.seriesName}</div>
    `;'''

new_meta = '''    const thumbH = Math.max(8, Math.round(brick.height * 0.45));
    card.innerHTML = `
      <div style="width:36px; height:${thumbH}px; background:${brick.color}; border:1px solid rgba(0,0,0,0.3); border-radius:3px; box-shadow:0 2px 4px rgba(0,0,0,0.3);"></div>
      <div class="card-name">${brick.name}</div>
      <div class="card-meta">${brick.studs} 凸粒 · ${brick.heightType || '積木'}</div>
    `;'''

assert old_meta in text, "old_meta not found"
text = text.replace(old_meta, new_meta, 1)

with open(path, 'w', encoding='utf-8') as f:
    f.write(text)

print("Successfully updated flat & tall bricks in lego_tower!")
