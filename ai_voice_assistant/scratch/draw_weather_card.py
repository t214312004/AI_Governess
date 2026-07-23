import os
from PIL import Image, ImageDraw, ImageFont

def create_weather_image(output_path):
    width, height = 1000, 750
    # Create image with dark slate background
    img = Image.new("RGB", (width, height), color="#0F172A")
    draw = ImageDraw.Draw(img)

    # Fonts
    font_path = "C:\\Windows\\Fonts\\msjh.ttc"
    font_path_bd = "C:\\Windows\\Fonts\\msjhbd.ttc"
    
    font_title = ImageFont.truetype(font_path_bd, 32)
    font_subtitle = ImageFont.truetype(font_path, 20)
    font_card_header = ImageFont.truetype(font_path_bd, 22)
    font_body = ImageFont.truetype(font_path, 18)
    font_body_bold = ImageFont.truetype(font_path_bd, 18)
    font_small = ImageFont.truetype(font_path, 15)

    # Header section
    draw.rectangle([(0, 0), (1000, 90)], fill="#1E293B")
    draw.text((40, 22), "台北內湖與全台灣天氣 - 颱風特別預報", font=font_title, fill="#F8FAFC")
    draw.text((40, 60), "預報時間：2026年7月24日 | 中央氣象署海上颱風警報中", font=font_subtitle, fill="#94A3B8")

    # Card 1: Taipei Neihu Details (Left panel)
    # Box bounds: x=(40, 480), y=(120, 700)
    draw.rounded_rectangle([(40, 120), (480, 700)], radius=16, fill="#1E293B", outline="#38BDF8", width=2)
    
    # Title bar inside Card 1
    draw.rounded_rectangle([(55, 135), (465, 180)], radius=8, fill="#0284C7")
    draw.text((70, 145), "📍 台北市內湖區區域預報", font=font_card_header, fill="#FFFFFF")

    items_c1 = [
        ("氣溫範圍", "26°C - 34°C (體感偏熱)", "#F8FAFC"),
        ("降雨機率", "60% (午後至晚上雨勢較明顯)", "#38BDF8"),
        ("天氣狀況", "多雲轉局部短暫雷陣雨", "#F8FAFC"),
        ("相對濕度", "80% (體感潮濕)", "#F8FAFC"),
        ("空氣品質", "PM2.5 約 12 μg/m³ (良好)", "#4ADE80"),
        ("主要影響", "受颱風外圍環流影響", "#F59E0B"),
    ]

    y_pos = 205
    for label, val, val_color in items_c1:
        draw.text((70, y_pos), f"• {label}：", font=font_body_bold, fill="#CBD5E1")
        draw.text((180, y_pos), val, font=font_body, fill=val_color)
        y_pos += 45

    # Tips box at bottom of Card 1
    draw.rounded_rectangle([(65, 500), (455, 675)], radius=12, fill="#0F172A", outline="#475569", width=1)
    draw.text((80, 515), "💡 愛管家貼心提醒", font=font_card_header, fill="#F59E0B")
    draw.text((80, 555), "1. 午後到傍晚有局部大雨，出門必備雨具。", font=font_small, fill="#E2E8F0")
    draw.text((80, 585), "2. 高溫與濕度較高，請多補充水分防暑。", font=font_small, fill="#E2E8F0")
    draw.text((80, 615), "3. 晚間返家路上注意防風與低窪淹水。", font=font_small, fill="#E2E8F0")

    # Card 2: Typhoon Details (Right panel)
    # Box bounds: x=(520, 960), y=(120, 700)
    draw.rounded_rectangle([(520, 120), (960, 700)], radius=16, fill="#1E293B", outline="#F43F5E", width=2)
    
    draw.rounded_rectangle([(535, 135), (945, 180)], radius=8, fill="#E11D48")
    draw.text((550, 145), "🌀 第12號颱風動態與全台影響", font=font_card_header, fill="#FFFFFF")

    items_c2 = [
        ("警報等級", "海上颱風警報 (23:30 發布)", "#F43F5E"),
        ("警戒區域", "巴士海峽、東沙島海面", "#F8FAFC"),
        ("動態路徑", "通過巴士海峽，朝廣東前進", "#F8FAFC"),
        ("最劇時段", "7月24日晚間 - 7月25日全天", "#F59E0B"),
        ("花東南部", "受外圍環流影響，局部豪雨", "#F8FAFC"),
        ("沿海風浪", "浪高3公尺以上，陣風8-9級", "#F8FAFC"),
    ]

    y_pos = 205
    for label, val, val_color in items_c2:
        draw.text((550, y_pos), f"• {label}：", font=font_body_bold, fill="#CBD5E1")
        draw.text((660, y_pos), val, font=font_body, fill=val_color)
        y_pos += 45

    # Coast alert box
    draw.rounded_rectangle([(545, 500), (935, 675)], radius=12, fill="#0F172A", outline="#475569", width=1)
    draw.text((560, 515), "⚠️ 海邊與觀浪安全警戒", font=font_card_header, fill="#F43F5E")
    draw.text((560, 555), "• 海警發布期間請嚴禁前往海邊觀浪或水上活動。", font=font_small, fill="#E2E8F0")
    draw.text((560, 585), "• 山區請留意土石鬆軟，北部地區請做好防風。", font=font_small, fill="#E2E8F0")
    draw.text((560, 615), "• 預計26日颱風逐漸遠離廣東方向。", font=font_small, fill="#E2E8F0")

    # Save image
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    img.save(output_path, "PNG")
    print(f"Saved Traditional Chinese weather card to {output_path}")

if __name__ == "__main__":
    out = "C:\\vibe_coding_projects\\AI_Governess\\AI_Governess\\ai_voice_assistant\\agent_workspace\\tool_payloads\\whiteboard\\assets\\weather_tc_map.png"
    create_weather_image(out)
