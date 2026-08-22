# -*- coding: utf-8 -*-
"""表现层：把老师对比数据渲染成「深科技磨砂玻璃」表格图片 / 文字。

图片依赖 Pillow（astrbot 已自带），懒加载；文字版不依赖任何外部库。
"""
import io
from pathlib import Path

# 中文字体候选
_FONTS = [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\simsun.ttc"]


def _font_path():
    return next((p for p in _FONTS if Path(p).exists()), None)


def teacher_rows_to_text(display_name, rows) -> str:
    """文字版老师对比表（无图片时的兜底/给 LLM 的文字总结）。"""
    lines = [f"「{display_name}」任课老师对比："]
    for r in rows[:8]:
        lines.append(f"- {r['teacher']}：评分 {r['rating']}/5，评价 {r['review_count']} 条")
        if r.get("summary"):
            lines.append(f"  评价总结：{r['summary']}")
        for s in (r.get("samples") or [])[:3]:
            c = (s.get("c") or "").strip()
            if c:
                lines.append(f"  学生原话：{c[:80]}")
    return "\n".join(lines)


def render_teacher_table(display_name, rows) -> bytes:
    """生成「深科技磨砂玻璃」老师对比表图片，返回 PNG 字节。"""
    from PIL import Image, ImageDraw, ImageFont, ImageFilter

    fp = _font_path()
    if not fp:
        raise RuntimeError("未找到中文字体")

    def font(sz):
        return ImageFont.truetype(fp, sz)

    # ---- 布局 ----
    W, pad = 920, 22
    title_h, head_h, line_h = 60, 40, 26
    col_t, col_r, col_n = 150, 72, 88
    col_c = W - pad * 2 - col_t - col_r - col_n
    f_title, f_head, f_body = font(23), font(15), font(14)

    # ---- 测量/换行 ----
    probe = Image.new("RGB", (1, 1), "white")
    pd = ImageDraw.Draw(probe)

    def wrap(text, maxw):
        lines, cur = [], ""
        for ch in text:
            if ch == "\n":
                if cur:
                    lines.append(cur)
                cur = ""
                continue
            if cur and pd.textlength(cur + ch, font=f_body) > maxw:
                lines.append(cur)
                cur = ch
            else:
                cur += ch
        if cur:
            lines.append(cur)
        return lines or [""]

    def short_comment(c):
        c = (c or "").strip().replace("\t", " ")
        return c if len(c) <= 90 else c[:90] + "…"

    blocks = []
    for r in rows[:6]:
        cell = []
        summary = (r.get("summary") or "").strip()
        if summary:
            cell = wrap(summary, col_c)[:3]
        else:
            for s in (r.get("samples") or [])[:1]:
                for ln in wrap(short_comment(s.get("c")) or "(暂无评价)", col_c):
                    cell.append(ln)
        if not cell:
            cell = ["(暂无评价总结)"]
        blocks.append((r, cell))

    def row_h(cell):
        return max(line_h * len(cell) + 20, 54)

    body_h = sum(row_h(cell) for _, cell in blocks)
    H = pad + title_h + head_h + body_h + pad

    # ---- 背景：深空灰蓝渐变 ----
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    top_c, bottom_c = (7, 13, 28), (18, 32, 56)
    for y in range(H):
        t = y / max(H, 1)
        c = tuple(int(top_c[i] + (bottom_c[i] - top_c[i]) * t) for i in range(3))
        ImageDraw.Draw(img).line([(0, y), (W, y)], fill=c + (255,))

    # ---- 背景柔光（青色，中上偏右）----
    _glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(_glow)
    gx, gy = int(W * 0.72), int(H * 0.26)
    for radius, alpha in [(230, 8), (150, 12), (90, 18)]:
        gd.ellipse([gx - radius, gy - radius, gx + radius, gy + radius], fill=(0, 240, 255, alpha))
    img.alpha_composite(_glow.filter(ImageFilter.GaussianBlur(60)))

    # ---- 网格线（静态）----
    _grid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gdd = ImageDraw.Draw(_grid)
    for x in range(0, W, 44):
        gdd.line([(x, 0), (x, H)], fill=(120, 180, 255, 20))
    for y in range(0, H, 44):
        gdd.line([(0, y), (W, y)], fill=(120, 180, 255, 20))
    img.alpha_composite(_grid)

    # ---- 扫描线（静态，营造监控感）----
    _scan = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sdd = ImageDraw.Draw(_scan)
    for y in range(pad, H - pad, 5):
        sdd.line([(pad, y), (W - pad, y)], fill=(255, 255, 255, 6))
    img.alpha_composite(_scan)

    # ---- 磨砂玻璃面板：发光边框 + 半透明玻璃填充 ----
    panel_rect = [pad - 8, pad - 8, W - pad + 8, H - pad + 8]
    _border = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(_border).rounded_rectangle(panel_rect, radius=18, outline=(0, 200, 255, 190), width=3)
    img.alpha_composite(_border.filter(ImageFilter.GaussianBlur(4)))
    _glass = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(_glass).rounded_rectangle(panel_rect, radius=18, fill=(255, 255, 255, 14))
    img.alpha_composite(_glass)
    ImageDraw.Draw(img).rounded_rectangle(panel_rect, radius=18, outline=(0, 220, 255, 220), width=1)

    # ---- 标题（青色光晕 + 浅色文字）----
    _tg = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(_tg).text((pad, pad), f"「{display_name}」任课老师对比", font=f_title, fill=(0, 240, 255, 255))
    img.alpha_composite(_tg.filter(ImageFilter.GaussianBlur(4)))
    ImageDraw.Draw(img).text((pad, pad), f"「{display_name}」任课老师对比", font=f_title, fill=(224, 246, 255, 255))

    # ---- 表头带（rgba 白 0.1）+ 底部青色渐变光条 ----
    hy = pad + title_h
    _head = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(_head).rectangle([pad, hy, W - pad, hy + head_h], fill=(255, 255, 255, 26))
    img.alpha_composite(_head)
    _bar = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bdd = ImageDraw.Draw(_bar)
    half = (W - pad) / 2
    for x in range(pad, W - pad):
        t = abs((x - W / 2) / half)
        a = int(200 * (1 - t))
        bdd.line([(x, hy + head_h), (x, hy + head_h + 3)], fill=(0, 220, 255, max(a, 0)))
    img.alpha_composite(_bar)

    draw = ImageDraw.Draw(img)
    draw.text((pad + 8, hy + 11), "教师", font=f_head, fill=(208, 232, 255, 255))
    draw.text((pad + col_t, hy + 11), "评分", font=f_head, fill=(120, 230, 255, 255))
    draw.text((pad + col_t + col_r, hy + 11), "评价数", font=f_head, fill=(208, 232, 255, 255))
    draw.text((pad + col_t + col_r + col_n, hy + 11), "评价要点", font=f_head, fill=(208, 232, 255, 255))

    # ---- 数据行 ----
    y = hy + head_h
    for r, cell in blocks:
        rh = row_h(cell)
        _sep = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(_sep).line([(pad, y), (W - pad, y)], fill=(120, 200, 255, 34), width=1)
        img.alpha_composite(_sep)
        draw.text((pad + 8, y + 16), r["teacher"], font=f_body, fill=(228, 242, 255, 255))
        rating = r.get("rating") or 0
        rtext = f"{rating}/5"
        _rg = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(_rg).text((pad + col_t, y + 16), rtext, font=f_body, fill=(0, 240, 255, 255))
        img.alpha_composite(_rg.filter(ImageFilter.GaussianBlur(3)))
        draw.text((pad + col_t, y + 16), rtext, font=f_body, fill=(0, 240, 255, 255))
        draw.text((pad + col_t + col_r, y + 16), str(r.get("review_count") or 0), font=f_body, fill=(200, 220, 235, 255))
        x = pad + col_t + col_r + col_n
        cy = y + 16
        for ln in cell:
            draw.text((x, cy), ln, font=f_body, fill=(210, 226, 240, 255))
            cy += line_h
        y += rh

    # ---- 科技角标（四角 L 形）----
    for cx, cy_, dx, dy in [
        (pad - 8, pad - 8, 1, 1), (W - pad + 8, pad - 8, -1, 1),
        (pad - 8, H - pad + 8, 1, -1), (W - pad + 8, H - pad + 8, -1, -1),
    ]:
        draw.line([(cx, cy_), (cx + dx * 26, cy_)], fill=(0, 220, 255, 200), width=2)
        draw.line([(cx, cy_), (cx, cy_ + dy * 26)], fill=(0, 220, 255, 200), width=2)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    return buf.getvalue()
