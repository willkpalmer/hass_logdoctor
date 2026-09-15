"""Generate a skeuomorphic 'Log Doctor' icon: a glossy tile with a paper
log document (lines of text, one flagged) and a stethoscope draped over it.

Palette (5 colors total):
  NAVY_DARK - tile gradient dark stop / outlines
  BLUE_LIGHT - tile gradient light stop
  PAPER      - document paper
  SLATE      - stethoscope metal / log text lines
  RED        - accent: earpieces + flagged log line
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "icon.png"

SIZE = 512
S = SIZE  # shorthand

NAVY_DARK = (16, 38, 68, 255)
BLUE_LIGHT = (86, 150, 210, 255)
PAPER = (248, 245, 236, 255)
SLATE = (96, 108, 122, 255)
SLATE_LIGHT = (150, 160, 172, 255)  # tint of SLATE, not a new color
RED = (199, 62, 62, 255)
RED_LIGHT = (224, 110, 100, 255)  # tint of RED

WHITE = (255, 255, 255, 255)
BLACK = (0, 0, 0, 255)


def solid(color, size=(S, S)):
    return Image.new("RGBA", size, color)


def linear_gradient_mask(size, angle_deg=45):
    """Grayscale L-mode gradient mask (0..255), rotated, then cropped back."""
    base = Image.linear_gradient("L").resize((size[0] * 2, size[1] * 2))
    rotated = base.rotate(angle_deg, expand=False)
    left = (rotated.width - size[0]) // 2
    top = (rotated.height - size[1]) // 2
    return rotated.crop((left, top, left + size[0], top + size[1]))


def radial_gradient_mask(size, center=None, radius=None):
    base = Image.radial_gradient("L").resize(size)
    return base


def drop_shadow(alpha_mask: Image.Image, offset=(0, 10), blur=14, opacity=110):
    """Build an RGBA shadow layer from a shape's alpha mask."""
    shadow = Image.new("RGBA", alpha_mask.size, (0, 0, 0, 0))
    solid_black = Image.new("RGBA", alpha_mask.size, (0, 0, 0, opacity))
    shadow = Image.composite(solid_black, shadow, alpha_mask)
    canvas = Image.new("RGBA", alpha_mask.size, (0, 0, 0, 0))
    canvas.paste(shadow, offset, shadow)
    return canvas.filter(ImageFilter.GaussianBlur(blur))


def main() -> None:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # ---- 1) Glossy rounded-square tile background ----
    tile_radius = int(S * 0.22)
    tile_mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(tile_mask).rounded_rectangle(
        [0, 0, S - 1, S - 1], radius=tile_radius, fill=255
    )

    grad_mask = linear_gradient_mask((S, S), angle_deg=35)
    tile_grad = Image.composite(solid(BLUE_LIGHT), solid(NAVY_DARK), grad_mask)
    tile = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    tile.paste(tile_grad, (0, 0), tile_mask)

    # subtle inner shading: darken bottom-right edge slightly for depth
    edge_shadow = Image.new("L", (S, S), 0)
    ImageDraw.Draw(edge_shadow).rounded_rectangle(
        [0, 0, S - 1, S - 1], radius=tile_radius, outline=255, width=int(S * 0.03)
    )
    edge_shadow = edge_shadow.filter(ImageFilter.GaussianBlur(S * 0.02))
    darken = Image.new("RGBA", (S, S), (0, 0, 0, 60))
    tile = Image.composite(darken, Image.new("RGBA", (S, S), (0, 0, 0, 0)), edge_shadow) \
        .convert("RGBA")
    # recombine: base tile + darken overlay, masked to tile shape
    combined = tile_grad.copy()
    edge_overlay = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    edge_overlay.paste(Image.new("RGBA", (S, S), (0, 0, 0, 70)), (0, 0), edge_shadow)
    combined = Image.alpha_composite(combined, edge_overlay)
    tile_final = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    tile_final.paste(combined, (0, 0), tile_mask)

    # glossy highlight: soft bright ellipse in the upper portion
    gloss = Image.new("L", (S, S), 0)
    gd = ImageDraw.Draw(gloss)
    gd.ellipse(
        [S * 0.05, -S * 0.25, S * 0.95, S * 0.55], fill=130
    )
    gloss = gloss.filter(ImageFilter.GaussianBlur(S * 0.05))
    gloss_layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gloss_layer.paste(Image.new("RGBA", (S, S), (255, 255, 255, 255)), (0, 0), gloss)
    gloss_masked = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gloss_masked.paste(gloss_layer, (0, 0), tile_mask)
    tile_final = Image.alpha_composite(tile_final, gloss_masked)

    img = Image.alpha_composite(img, tile_final)

    # ---- 2) Paper document (rounded rect, slight shading), drop shadow ----
    doc_w, doc_h = int(S * 0.52), int(S * 0.60)
    doc_x = int(S * 0.20)
    doc_y = int(S * 0.20)
    doc_radius = int(S * 0.045)

    doc_mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(doc_mask).rounded_rectangle(
        [doc_x, doc_y, doc_x + doc_w, doc_y + doc_h], radius=doc_radius, fill=255
    )
    shadow_layer = drop_shadow(doc_mask, offset=(int(S * 0.02), int(S * 0.035)), blur=S * 0.03, opacity=130)
    img = Image.alpha_composite(img, shadow_layer)

    doc_grad_mask = linear_gradient_mask((S, S), angle_deg=60)
    doc_grad = Image.composite(solid(WHITE), solid(PAPER), doc_grad_mask)
    doc_layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    doc_layer.paste(doc_grad, (0, 0), doc_mask)
    img = Image.alpha_composite(img, doc_layer)

    # thin darker paper edge for definition
    edge = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ed = ImageDraw.Draw(edge)
    ed.rounded_rectangle(
        [doc_x, doc_y, doc_x + doc_w, doc_y + doc_h],
        radius=doc_radius,
        outline=(*NAVY_DARK[:3], 60),
        width=2,
    )
    img = Image.alpha_composite(img, edge)

    # ---- 3) Log text lines on the document (one flagged red) ----
    line_x0 = doc_x + int(doc_w * 0.14)
    line_x1 = doc_x + int(doc_w * 0.86)
    line_ys = [doc_y + int(doc_h * f) for f in (0.20, 0.33, 0.46, 0.59, 0.72)]
    line_w = int(S * 0.018)
    flagged_index = 2

    draw = ImageDraw.Draw(img)
    for i, ly in enumerate(line_ys):
        color = RED if i == flagged_index else SLATE
        # vary line length a bit for a natural "text" feel, shorten last line
        x1 = line_x1 if i != len(line_ys) - 1 else doc_x + int(doc_w * 0.60)
        draw.line([(line_x0, ly), (x1, ly)], fill=color, width=line_w)
        draw.ellipse(
            [line_x0 - line_w // 2, ly - line_w // 2, line_x0 + line_w // 2, ly + line_w // 2],
            fill=color,
        )
        draw.ellipse(
            [x1 - line_w // 2, ly - line_w // 2, x1 + line_w // 2, ly + line_w // 2],
            fill=color,
        )
    # small warning dot to the left of the flagged line
    fy = line_ys[flagged_index]
    dot_r = int(S * 0.018)
    draw.ellipse(
        [line_x0 - int(S * 0.06) - dot_r, fy - dot_r, line_x0 - int(S * 0.06) + dot_r, fy + dot_r],
        fill=RED,
    )

    # ---- 4) Stethoscope draped across the tile/document ----
    tube_w = int(S * 0.028)

    # Tube: a large looping arc from upper-right, around, ending at the
    # chest piece resting on the lower-left of the document.
    steth = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    sd = ImageDraw.Draw(steth)

    # Neck/tube down from the earpieces (upper right area) curving to the
    # chest piece near the bottom of the document.
    ear_x, ear_y = int(S * 0.80), int(S * 0.14)
    bend_x, bend_y = int(S * 0.86), int(S * 0.52)
    chest_x, chest_y = int(S * 0.40), int(S * 0.78)

    # tube shadow first (drawn on the main image, offset slightly)
    tube_points = [(ear_x, ear_y), (bend_x, bend_y), (chest_x, chest_y)]

    def draw_smooth_tube(target_draw, points, width, fill):
        # Approximate a smooth curve with a quadratic bezier sampled densely.
        (x0, y0), (cx, cy), (x2, y2) = points
        steps = 60
        prev = None
        for i in range(steps + 1):
            t = i / steps
            x = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t ** 2 * x2
            y = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t ** 2 * y2
            if prev is not None:
                target_draw.line([prev, (x, y)], fill=fill, width=width)
            prev = (x, y)
        # round caps
        r = width // 2
        target_draw.ellipse([x0 - r, y0 - r, x0 + r, y0 + r], fill=fill)
        target_draw.ellipse([x2 - r, y2 - r, x2 + r, y2 + r], fill=fill)

    # shadow of tube on the tile/document
    tube_shadow_mask = Image.new("L", (S, S), 0)
    tsd = ImageDraw.Draw(tube_shadow_mask)
    draw_smooth_tube(tsd, tube_points, tube_w + 6, 255)
    tube_shadow_mask = tube_shadow_mask.filter(ImageFilter.GaussianBlur(S * 0.012))
    shadow_layer2 = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    shadow_layer2.paste(Image.new("RGBA", (S, S), (0, 0, 0, 90)), (int(S * 0.012), int(S * 0.016)), tube_shadow_mask)
    img = Image.alpha_composite(img, shadow_layer2)

    # main tube (slate) + a thin lighter highlight stripe for a rounded look
    draw_smooth_tube(sd, tube_points, tube_w, SLATE)
    # highlight: slightly thinner, offset up-left
    (x0, y0), (cx, cy), (x2, y2) = tube_points
    hi_points = [(x0 - 3, y0 - 3), (cx - 3, cy - 3), (x2 - 3, y2 - 3)]
    draw_smooth_tube(sd, hi_points, max(2, tube_w // 3), SLATE_LIGHT)

    img = Image.alpha_composite(img, steth)
    draw = ImageDraw.Draw(img)

    # earpieces: two small red capsules at the top of the tube
    for dx in (-int(S * 0.05), int(S * 0.05)):
        ex, ey = ear_x + dx, ear_y - int(S * 0.02)
        er = int(S * 0.028)
        draw.ellipse([ex - er, ey - er, ex + er, ey + er], fill=RED)
        draw.ellipse(
            [ex - er * 0.4, ey - er * 0.6, ex + er * 0.1, ey - er * 0.1],
            fill=RED_LIGHT,
        )
    draw.line([(ear_x - int(S * 0.05), ear_y - int(S * 0.02)),
               (ear_x + int(S * 0.05), ear_y - int(S * 0.02))], fill=SLATE, width=int(tube_w * 0.7))

    # chest piece (diaphragm): metallic disc with radial shading + shadow
    disc_r = int(S * 0.075)
    disc_mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(disc_mask).ellipse(
        [chest_x - disc_r, chest_y - disc_r, chest_x + disc_r, chest_y + disc_r], fill=255
    )
    disc_shadow = drop_shadow(disc_mask, offset=(int(S * 0.012), int(S * 0.018)), blur=S * 0.015, opacity=120)
    img = Image.alpha_composite(img, disc_shadow)

    radial = radial_gradient_mask((disc_r * 2, disc_r * 2))
    disc_grad = Image.composite(
        solid(WHITE, (disc_r * 2, disc_r * 2)),
        solid(SLATE, (disc_r * 2, disc_r * 2)),
        radial,
    )
    disc_layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    disc_crop_mask = Image.new("L", (disc_r * 2, disc_r * 2), 0)
    ImageDraw.Draw(disc_crop_mask).ellipse([0, 0, disc_r * 2 - 1, disc_r * 2 - 1], fill=255)
    disc_layer.paste(disc_grad, (chest_x - disc_r, chest_y - disc_r), disc_crop_mask)
    img = Image.alpha_composite(img, disc_layer)

    ring = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    rd = ImageDraw.Draw(ring)
    rd.ellipse(
        [chest_x - disc_r, chest_y - disc_r, chest_x + disc_r, chest_y + disc_r],
        outline=(*NAVY_DARK[:3], 130),
        width=3,
    )
    # small glossy highlight arc on the disc
    rd.arc(
        [chest_x - disc_r * 0.6, chest_y - disc_r * 0.7, chest_x + disc_r * 0.2, chest_y - disc_r * 0.1],
        start=200, end=340, fill=(255, 255, 255, 160), width=4,
    )
    img = Image.alpha_composite(img, ring)

    img.save(OUTPUT_PATH)
    print(f"saved {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
