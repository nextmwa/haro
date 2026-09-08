import enum
import math
from typing import Protocol

from PIL import Image, ImageDraw


class Expression(enum.Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING_HAPPY = "speaking_happy"
    SPEAKING_SAD = "speaking_sad"
    SPEAKING_CONFUSED = "speaking_confused"
    SPEAKING_NEUTRAL = "speaking_neutral"
    ERROR = "error"
    SETUP = "setup"


class DisplayDevice(Protocol):
    width: int
    height: int

    def display(self, image: Image.Image) -> None: ...


_EMOTION_TO_EXPRESSION = {
    "happy": Expression.SPEAKING_HAPPY,
    "sad": Expression.SPEAKING_SAD,
    "confused": Expression.SPEAKING_CONFUSED,
    "neutral": Expression.SPEAKING_NEUTRAL,
}


def expression_for_emotion(value: str) -> Expression:
    return _EMOTION_TO_EXPRESSION.get(value, Expression.SPEAKING_NEUTRAL)


# --- Cozmo-style drawing primitives -------------------------------------
#
# Anki Cozmo's face reads as soft, rounded "leaf" eyes on black that
# squash, stretch and tilt to carry emotion, with a simple rounded mouth
# underneath. We approximate that on a 1-bit OLED with rounded-rectangle
# eyes -- tilted per expression by drawing on a small canvas and rotating,
# since a single ImageDraw call can't rotate -- plus round-capped arcs for
# the mouth instead of plain thin lines.

def _eye(image: Image.Image, cx: int, cy: int, w: int, h: int, radius: int, angle: float = 0.0) -> None:
    radius = min(radius, w // 2, h // 2)
    if not angle:
        ImageDraw.Draw(image).rounded_rectangle(
            (cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2), radius=radius, fill=1,
        )
        return
    pad = max(w, h)
    canvas = Image.new("L", (w + pad, h + pad), 0)
    ImageDraw.Draw(canvas).rounded_rectangle(
        (pad // 2, pad // 2, pad // 2 + w, pad // 2 + h), radius=radius, fill=255,
    )
    canvas = canvas.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    shape = canvas.point(lambda p: 255 if p > 127 else 0).convert("1", dither=Image.Dither.NONE)
    image.paste(shape, (cx - shape.width // 2, cy - shape.height // 2), shape)


def _capped_arc(draw: ImageDraw.ImageDraw, bbox: tuple[int, int, int, int], start: float, end: float, width_px: int) -> None:
    """An arc with small filled circles at both ends, for Cozmo's soft rounded strokes."""
    draw.arc(bbox, start=start, end=end, fill=1, width=width_px)
    x0, y0, x1, y1 = bbox
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx, ry = (x1 - x0) / 2, (y1 - y0) / 2
    cap = max(1, width_px // 2)
    for ang in (start, end):
        rad = math.radians(ang)
        px, py = cx + rx * math.cos(rad), cy + ry * math.sin(rad)
        draw.ellipse((px - cap, py - cap, px + cap, py + cap), fill=1)


def _eye_smile(image: Image.Image, cx: int, cy: int, w: int, h: int, width_px: int) -> None:
    """A happy, upward-curved squint ('^') instead of a rounded-rect eye."""
    bbox = (cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2)
    _capped_arc(ImageDraw.Draw(image), bbox, start=190, end=350, width_px=width_px)


def _eye_x(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int, width_px: int) -> None:
    draw.line((cx - r, cy - r, cx + r, cy + r), fill=1, width=width_px)
    draw.line((cx - r, cy + r, cx + r, cy - r), fill=1, width=width_px)
    cap = width_px // 2
    for dx, dy in ((-r, -r), (r, -r), (-r, r), (r, r)):
        draw.ellipse((cx + dx - cap, cy + dy - cap, cx + dx + cap, cy + dy + cap), fill=1)


def render_expression(expression: Expression, size: tuple[int, int] = (128, 64)) -> Image.Image:
    width, height = size
    image = Image.new("1", size, 0)
    draw = ImageDraw.Draw(image)

    eye_cy = int(height * 0.38)
    eye_w, eye_h = int(width * 0.20), int(height * 0.32)
    eye_radius = min(eye_w, eye_h) // 2  # pill-shaped ends, Cozmo's "leaf" eye
    left_x, right_x = int(width * 0.30), int(width * 0.70)

    mouth_cy = int(height * 0.78)
    mouth_half_w = int(width * 0.18)
    mouth_cx = width // 2

    if expression == Expression.SPEAKING_HAPPY:
        _eye_smile(image, left_x, eye_cy, eye_w + 4, eye_h, width_px=3)
        _eye_smile(image, right_x, eye_cy, eye_w + 4, eye_h, width_px=3)
        _capped_arc(
            draw, (mouth_cx - mouth_half_w, mouth_cy - 14, mouth_cx + mouth_half_w, mouth_cy + 10),
            start=15, end=165, width_px=3,
        )

    elif expression == Expression.SPEAKING_SAD:
        _eye(image, left_x, eye_cy, eye_w, eye_h, eye_radius, angle=-22)
        _eye(image, right_x, eye_cy, eye_w, eye_h, eye_radius, angle=22)
        _capped_arc(
            draw, (mouth_cx - mouth_half_w, mouth_cy, mouth_cx + mouth_half_w, mouth_cy + 22),
            start=200, end=340, width_px=3,
        )

    elif expression == Expression.SPEAKING_CONFUSED:
        _eye(image, left_x, eye_cy, eye_w, eye_h, eye_radius, angle=0)
        _eye(image, right_x, int(eye_cy * 0.8), eye_w, eye_h, eye_radius, angle=22)
        draw.line(
            (mouth_cx - mouth_half_w, mouth_cy, mouth_cx - mouth_half_w // 3, mouth_cy + 7,
             mouth_cx + mouth_half_w // 3, mouth_cy - 7, mouth_cx + mouth_half_w, mouth_cy),
            fill=1, width=3, joint="curve",
        )

    elif expression == Expression.THINKING:
        think_h = int(eye_h * 0.6)
        think_radius = min(eye_w, think_h) // 3
        _eye(image, left_x, eye_cy, eye_w, think_h, think_radius, angle=-18)
        _eye(image, right_x, eye_cy, eye_w, think_h, think_radius, angle=-18)
        dot_r = max(2, height // 20)
        for step in (-1, 0, 1):
            dx = mouth_cx + step * dot_r * 3
            draw.ellipse((dx - dot_r, mouth_cy - dot_r, dx + dot_r, mouth_cy + dot_r), fill=1)

    elif expression == Expression.ERROR:
        x_width = max(2, eye_w // 8)
        _eye_x(draw, left_x, eye_cy, eye_w // 2, width_px=x_width)
        _eye_x(draw, right_x, eye_cy, eye_w // 2, width_px=x_width)
        draw.rounded_rectangle(
            (mouth_cx - mouth_half_w // 2, mouth_cy - 2, mouth_cx + mouth_half_w // 2, mouth_cy + 2),
            radius=2, fill=1,
        )

    elif expression == Expression.SETUP:
        dot_r = max(2, eye_h // 5)
        draw.ellipse((left_x - dot_r, eye_cy - dot_r, left_x + dot_r, eye_cy + dot_r), fill=1)
        draw.ellipse((right_x - dot_r, eye_cy - dot_r, right_x + dot_r, eye_cy + dot_r), fill=1)
        draw.text((mouth_cx - 20, mouth_cy - 6), "SETUP", fill=1)

    elif expression == Expression.LISTENING:
        _eye(image, left_x, eye_cy, int(eye_w * 1.05), int(eye_h * 1.25), eye_radius, angle=0)
        _eye(image, right_x, eye_cy, int(eye_w * 1.05), int(eye_h * 1.25), eye_radius, angle=0)
        r = max(2, height // 16)
        draw.ellipse((mouth_cx - r, mouth_cy - r, mouth_cx + r, mouth_cy + r), outline=1, width=2)

    elif expression == Expression.SPEAKING_NEUTRAL:
        _eye(image, left_x, eye_cy, eye_w, eye_h, eye_radius, angle=0)
        _eye(image, right_x, eye_cy, eye_w, eye_h, eye_radius, angle=0)
        mouth_r = max(3, height // 10)
        draw.rounded_rectangle(
            (mouth_cx - mouth_half_w // 2, mouth_cy - mouth_r, mouth_cx + mouth_half_w // 2, mouth_cy + mouth_r),
            radius=mouth_r, fill=1,
        )

    else:  # IDLE
        _eye(image, left_x, eye_cy, eye_w, eye_h, eye_radius, angle=0)
        _eye(image, right_x, eye_cy, eye_w, eye_h, eye_radius, angle=0)
        draw.rounded_rectangle(
            (mouth_cx - mouth_half_w // 2, mouth_cy - 2, mouth_cx + mouth_half_w // 2, mouth_cy + 2),
            radius=2, fill=1,
        )

    return image


class FaceDisplay:
    def __init__(self, device: DisplayDevice) -> None:
        self._device = device

    def show(self, expression: Expression) -> None:
        image = render_expression(expression, (self._device.width, self._device.height))
        self._device.display(image)
