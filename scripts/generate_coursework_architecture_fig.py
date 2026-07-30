from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


OUT = Path("docs/fig-system-architecture.png")
W, H = 2400, 1200


def main() -> None:
    img = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)

    font_path = "C:/Windows/Fonts/simhei.ttf"
    font_title = ImageFont.truetype(font_path, 58)
    font_node = ImageFont.truetype(font_path, 36)
    font_small = ImageFont.truetype(font_path, 30)
    font_note = ImageFont.truetype(font_path, 28)

    blue = "#2563eb"
    border = "#4065b0"
    fill = "#eef4ff"
    text = "#111827"
    line = "#4b5563"
    orange = "#b45309"

    title = "教材教学视频自动生成系统流程"
    title_box = draw.textbbox((0, 0), title, font=font_title)
    draw.text(((W - (title_box[2] - title_box[0])) / 2, 45), title, font=font_title, fill=blue)

    nodes_top = [
        ("教材输入", "PDF/DOCX"),
        ("教材解析", "文本/图片"),
        ("教学计划", "目标/活动/检测"),
        ("讲稿生成", "旁白分段"),
        ("结构化故事板", "页面/元素/动画"),
    ]
    nodes_bottom = [
        ("多智能体审核", "Review/Repair"),
        ("TTS配音", "时长回写"),
        ("HTML动画", "模板渲染"),
        ("浏览器录制", "按真实时长翻页"),
        ("有声教学视频", "MP4"),
    ]

    box_w, box_h = 360, 150
    xs = [95, 515, 935, 1355, 1775]
    y_top, y_bottom = 230, 720

    def centered_text(rect, lines, fonts):
        x1, y1, x2, y2 = rect
        boxes = [draw.textbbox((0, 0), value, font=font) for value, font in zip(lines, fonts)]
        heights = [box[3] - box[1] for box in boxes]
        total_h = sum(heights) + 10 * (len(lines) - 1)
        y = y1 + (y2 - y1 - total_h) / 2 - 2
        for value, font, box, height in zip(lines, fonts, boxes, heights):
            width = box[2] - box[0]
            draw.text((x1 + (x2 - x1 - width) / 2, y), value, font=font, fill=text)
            y += height + 10

    def node(x, y, main_text, sub_text):
        rect = (x, y, x + box_w, y + box_h)
        draw.rounded_rectangle(rect, radius=22, fill=fill, outline=border, width=4)
        centered_text(rect, [main_text, sub_text], [font_node, font_small])

    def arrow(x1, y1, x2, y2, color=line, width=5):
        import math

        draw.line((x1, y1, x2, y2), fill=color, width=width)
        angle = math.atan2(y2 - y1, x2 - x1)
        size = 22
        points = [
            (x2, y2),
            (x2 - size * math.cos(angle - 0.45), y2 - size * math.sin(angle - 0.45)),
            (x2 - size * math.cos(angle + 0.45), y2 - size * math.sin(angle + 0.45)),
        ]
        draw.polygon(points, fill=color)

    for i, (main_text, sub_text) in enumerate(nodes_top):
        node(xs[i], y_top, main_text, sub_text)
    for i, (main_text, sub_text) in enumerate(nodes_bottom):
        node(xs[i], y_bottom, main_text, sub_text)

    for i in range(4):
        arrow(xs[i] + box_w + 5, y_top + box_h / 2, xs[i + 1] - 12, y_top + box_h / 2)
        arrow(xs[i] + box_w + 5, y_bottom + box_h / 2, xs[i + 1] - 12, y_bottom + box_h / 2)

    arrow(xs[4] + box_w / 2, y_top + box_h + 12, xs[0] + box_w / 2, y_bottom - 18)

    # Dashed repair path.
    repair_points = [
        (xs[0] + box_w / 2, y_bottom - 28),
        (xs[0] + box_w / 2, 610),
        (xs[4] + box_w / 2, 610),
        (xs[4] + box_w / 2, y_top + box_h + 24),
    ]
    import math

    for (x1, y1), (x2, y2) in zip(repair_points, repair_points[1:]):
        length = math.hypot(x2 - x1, y2 - y1)
        if length == 0:
            continue
        dash, gap = 28, 16
        ux, uy = (x2 - x1) / length, (y2 - y1) / length
        distance = 0
        while distance < length:
            start = distance
            end = min(distance + dash, length)
            draw.line((x1 + ux * start, y1 + uy * start, x1 + ux * end, y1 + uy * end), fill=orange, width=5)
            distance += dash + gap
    arrow(xs[4] + box_w / 2, y_top + box_h + 70, xs[4] + box_w / 2, y_top + box_h + 24, color=orange, width=5)

    label = "未通过时返修故事板"
    draw.rounded_rectangle((1005, 570, 1395, 650), radius=18, fill="white", outline=orange, width=3)
    label_box = draw.textbbox((0, 0), label, font=font_note)
    draw.text((1200 - (label_box[2] - label_box[0]) / 2, 590), label, font=font_note, fill=orange)

    note = "箭头表示自动生成流程，虚线表示审核未通过后的返修路径。"
    note_box = draw.textbbox((0, 0), note, font=font_note)
    draw.text(((W - (note_box[2] - note_box[0])) / 2, 1060), note, font=font_note, fill="#374151")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, dpi=(300, 300))


if __name__ == "__main__":
    main()
