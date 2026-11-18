"""Animated end screen ("Follow for more" / "Subscribe for more") added after each clip.

The animation is drawn with Pillow as a transparent PNG sequence (1080x1920, 30 fps) and
overlaid by ffmpeg on the clip's frozen last frame:

  0.00-0.30s  the frozen frame darkens
  0.10-0.55s  a card pops in: @handle, headline, button
  0.90-1.45s  a cursor moves to the button
  1.45-1.60s  click: the button presses, flips to "Following" / "Subscribed", ripple
  2.20-2.50s  the cursor fades; the card holds until the end

Rendered frames are cached in data/outros/<hash>/ so each style is drawn once.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from clipper import config

W, H = 1080, 1920
FPS = 30
DURATION = 3.0
VERSION = 2  # bump to re-render cached frames after changing the drawing code


@dataclass(frozen=True)
class OutroStyle:
    headline: str = "Follow for more"
    handle: str = ""                      # e.g. "@myclips"; hidden when empty
    button: str = "Follow"
    button_done: str = "Following"
    accent: str = "#0095F6"               # button colour before the click

    @staticmethod
    def for_platform(platform: str, handle: str = "") -> "OutroStyle":
        if platform == "youtube":
            return OutroStyle("Subscribe for more", handle, "Subscribe", "Subscribed", "#E62117")
        return OutroStyle("Follow for more", handle, "Follow", "Following", "#0095F6")


# ---- Fonts ------------------------------------------------------------------
_FONT_CANDIDATES = {
    "bold": ["segoeuib.ttf", "arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"],
    "semibold": ["seguisb.ttf", "segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"],
    "regular": ["segoeui.ttf", "arial.ttf", "Arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"],
}
_FONT_DIRS = [Path("C:/Windows/Fonts"), Path("/Library/Fonts"), Path("/System/Library/Fonts/Supplemental"),
              Path("/usr/share/fonts/truetype/dejavu"), Path("/usr/share/fonts/truetype/liberation")]


def _font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    for name in _FONT_CANDIDATES[weight]:
        for d in _FONT_DIRS:
            if (d / name).exists():
                return ImageFont.truetype(str(d / name), size)
    return ImageFont.load_default(size)


# ---- Easing -----------------------------------------------------------------
def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _span(t: float, a: float, b: float) -> float:
    return _clamp((t - a) / (b - a))


def _ease_out_cubic(x: float) -> float:
    return 1 - (1 - x) ** 3


def _ease_in_out(x: float) -> float:
    return 3 * x * x - 2 * x * x * x


def _ease_out_back(x: float) -> float:
    c1, c3 = 1.4, 2.4
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2


def _hex(color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    c = color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), alpha


# ---- Drawing ----------------------------------------------------------------
CARD_W = 860
BTN_W, BTN_H = 520, 116
CARD_Y = int(H * 0.52)  # card centre
CARD_PAD = 64


def _layout(style: OutroStyle) -> dict[str, float]:
    """Vertical positions (centres, from the card's top) so the content is balanced
    with or without a handle."""
    y = CARD_PAD
    handle_y = None
    if style.handle:
        handle_y = y + 23
        y += 46 + 22
    headline_y = y + 42
    y += 84 + 52
    btn_y = y + BTN_H / 2
    return {"card_h": y + BTN_H + CARD_PAD, "handle_y": handle_y, "headline_y": headline_y, "btn_y": btn_y}


def _button(style: OutroStyle, done: bool) -> Image.Image:
    img = Image.new("RGBA", (BTN_W, BTN_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bg = (236, 236, 236, 255) if done else _hex(style.accent)
    fg = (24, 24, 27, 255) if done else (255, 255, 255, 255)
    d.rounded_rectangle((0, 0, BTN_W - 1, BTN_H - 1), radius=BTN_H // 2, fill=bg)
    font = _font("bold", 46)
    label = style.button_done if done else style.button
    tw = d.textlength(label, font=font)
    icon_w, gap = 38, 18
    x = (BTN_W - (icon_w + gap + tw)) / 2
    cy = BTN_H / 2
    if done:  # check mark
        d.line([(x + 2, cy + 2), (x + 14, cy + 14), (x + 36, cy - 12)], fill=fg, width=8, joint="curve")
    else:     # plus
        d.line([(x + 4, cy), (x + 34, cy)], fill=fg, width=8)
        d.line([(x + 19, cy - 15), (x + 19, cy + 15)], fill=fg, width=8)
    d.text((x + icon_w + gap, cy), label, font=font, fill=fg, anchor="lm")
    return img


def _card(style: OutroStyle) -> Image.Image:
    """The card without its button (drawn separately so it can animate)."""
    pad = 60  # room for the shadow
    lay = _layout(style)
    card_h = int(lay["card_h"])
    img = Image.new("RGBA", (CARD_W + 2 * pad, card_h + 2 * pad), (0, 0, 0, 0))
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((pad, pad + 18, pad + CARD_W, pad + card_h + 18), radius=44,
                                             fill=(0, 0, 0, 110))
    img = Image.alpha_composite(img, shadow.filter(ImageFilter.GaussianBlur(26)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((pad, pad, pad + CARD_W, pad + card_h), radius=44, fill=(255, 255, 255, 255))

    cx = pad + CARD_W / 2
    if lay["handle_y"] is not None:
        d.text((cx, pad + lay["handle_y"]), style.handle, font=_font("semibold", 38),
               fill=(113, 113, 122, 255), anchor="mm")
    d.text((cx, pad + lay["headline_y"]), style.headline, font=_font("bold", 76),
           fill=(24, 24, 27, 255), anchor="mm")
    return img


def _cursor() -> Image.Image:
    """A simple arrow pointer, white with a dark outline, ~70 px tall."""
    s = 3  # draw large, then downsample for smooth edges
    pts = [(0, 0), (0, 52), (13, 40), (22, 62), (31, 58), (22, 37), (40, 37)]
    img = Image.new("RGBA", (46 * s, 70 * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    big = [(x * s + 4 * s, y * s + 3 * s) for x, y in pts]
    d.polygon(big, fill=(255, 255, 255, 255), outline=(24, 24, 27, 255), width=3 * s)
    return img.resize((46, 70), Image.LANCZOS)


def _with_opacity(img: Image.Image, opacity: float) -> Image.Image:
    if opacity >= 1:
        return img
    out = img.copy()
    out.putalpha(out.getchannel("A").point(lambda a: int(a * opacity)))
    return out


def _paste(canvas: Image.Image, img: Image.Image, cx: float, cy: float, scale: float = 1.0,
           opacity: float = 1.0) -> None:
    if scale != 1.0:
        img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.BICUBIC)
    img = _with_opacity(img, opacity)
    canvas.alpha_composite(img, (int(cx - img.width / 2), int(cy - img.height / 2)))


def render_frame(t: float, style: OutroStyle, assets: dict) -> Image.Image:
    frame = Image.new("RGBA", (W, H), (0, 0, 0, int(170 * _ease_out_cubic(_span(t, 0.0, 0.3)))))

    # Card: slide up + scale in with a small overshoot.
    p = _span(t, 0.10, 0.55)
    if p <= 0:
        return frame
    scale = 0.82 + 0.18 * _ease_out_back(p)
    dy = 170 * (1 - _ease_out_cubic(p))
    opacity = _ease_out_cubic(_span(t, 0.10, 0.35))
    _paste(frame, assets["card"], W / 2, CARD_Y + dy, scale, opacity)

    # Button: press on click, pop after the state flips.
    clicked = t >= 1.55
    press = 1 - 0.07 * math.sin(math.pi * _span(t, 1.45, 1.62))
    pop = 1 + 0.05 * math.sin(math.pi * _span(t, 1.62, 1.85))
    lay = assets["layout"]
    btn_y = CARD_Y + dy + scale * (lay["btn_y"] - lay["card_h"] / 2)
    btn = assets["btn_done"] if clicked else assets["btn"]
    _paste(frame, btn, W / 2, btn_y, scale * press * pop, opacity)

    # Ripple from the click point.
    r = _span(t, 1.52, 2.05)
    if 0 < r < 1:
        radius = 40 + 220 * _ease_out_cubic(r)
        ring = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(ring).ellipse((W / 2 - radius, btn_y - radius, W / 2 + radius, btn_y + radius),
                                     outline=_hex(style.accent, int(200 * (1 - r))), width=6)
        frame.alpha_composite(ring)

    # Cursor: glides in from the lower right, clicks, fades out.
    c_in = _span(t, 0.90, 1.45)
    if t >= 0.85 and t < 2.5:
        start = (W * 0.80, H * 0.86)
        end = (W / 2 + 40, btn_y + 18)
        k = _ease_in_out(c_in)
        x = start[0] + (end[0] - start[0]) * k
        y = start[1] + (end[1] - start[1]) * k
        c_scale = 1 - 0.15 * math.sin(math.pi * _span(t, 1.45, 1.62))
        c_op = _span(t, 0.85, 1.0) * (1 - _span(t, 2.2, 2.5))
        cur = assets["cursor"]
        if c_scale != 1:
            cur = cur.resize((int(cur.width * c_scale), int(cur.height * c_scale)), Image.LANCZOS)
        frame.alpha_composite(_with_opacity(cur, c_op), (int(x), int(y)))
    return frame


# ---- Cache ------------------------------------------------------------------
def frames_dir(style: OutroStyle) -> Path:
    """Render the PNG sequence once per style; returns the folder (000.png, 001.png, ...)."""
    key = hashlib.sha1(json.dumps({**asdict(style), "v": VERSION}, sort_keys=True).encode()).hexdigest()[:12]
    out = config.DATA_DIR / "outros" / key
    n = int(DURATION * FPS)
    if (out / f"{n - 1:03d}.png").exists():
        return out
    out.mkdir(parents=True, exist_ok=True)
    assets = {"card": _card(style), "btn": _button(style, False), "btn_done": _button(style, True),
              "cursor": _cursor(), "layout": _layout(style)}
    for i in range(n):
        render_frame(i / FPS, style, assets).save(out / f"{i:03d}.png", compress_level=1)
    (out / "style.json").write_text(json.dumps(asdict(style), indent=2), encoding="utf-8")
    return out


# ---- End pieces ---------------------------------------------------------------
PLATFORMS = ("instagram", "youtube")


def end_piece_name(clip_name: str, platform: str) -> str:
    return f"{clip_name}.end_{platform}.mp4"


def make_end_piece(clip: Path, dst: Path, style: OutroStyle) -> None:
    """3 s video: the clip's last frame, frozen, with the animation on top and silent audio.
    Encoded exactly like clips, so clip + end piece can be joined without re-encoding."""
    from clipper.media import AUDIO_ARGS, VIDEO_ARGS, ffmpeg, probe

    _, w, h = probe(clip)
    if (w, h) != (W, H):
        raise ValueError("End screens need a 1080x1920 clip")
    last = dst.with_suffix(".last.png")
    try:
        ffmpeg("-sseof", "-0.5", "-i", str(clip), "-update", "1", "-q:v", "2", str(last))
        frames = frames_dir(style)
        ffmpeg("-loop", "1", "-framerate", str(FPS), "-t", str(DURATION), "-i", str(last),
               "-framerate", str(FPS), "-i", str(frames / "%03d.png"),
               "-f", "lavfi", "-t", str(DURATION), "-i", "anullsrc=r=48000:cl=stereo",
               "-filter_complex", "[0:v][1:v]overlay=format=auto,format=yuv420p,setsar=1[v]",
               "-map", "[v]", "-map", "2:a", "-t", str(DURATION),
               *VIDEO_ARGS, *AUDIO_ARGS, "-movflags", "+faststart", str(dst))
    finally:
        last.unlink(missing_ok=True)


def add_end_pieces(clip: Path, handle: str = "") -> dict[str, str]:
    """Create the Instagram and YouTube end pieces next to the clip. Returns {platform: file}."""
    out = {}
    for platform in PLATFORMS:
        dst = clip.with_name(end_piece_name(clip.stem, platform))
        make_end_piece(clip, dst, OutroStyle.for_platform(platform, handle))
        out[platform] = dst.name
    return out


if __name__ == "__main__":  # python -m clipper.outro [instagram|youtube] [@handle]
    platform = sys.argv[1] if len(sys.argv) > 1 else "instagram"
    print(frames_dir(OutroStyle.for_platform(platform, sys.argv[2] if len(sys.argv) > 2 else "")))
