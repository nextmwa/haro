import enum
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


def render_expression(expression: Expression, size: tuple[int, int] = (128, 64)) -> Image.Image:
    width, height = size
    image = Image.new("1", size, 0)
    draw = ImageDraw.Draw(image)

    eye_y = height // 3
    eye_radius = max(2, height // 8)
    left_eye_x = width // 3
    right_eye_x = 2 * width // 3
    mouth_y = int(height * 0.7)
    mouth_half_width = width // 4
    mouth_cx = width // 2

    def open_eye(cx: int, cy: int, r: int) -> None:
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=1, fill=1)

    def closed_eye(cx: int, cy: int, r: int) -> None:
        draw.line((cx - r, cy, cx + r, cy), fill=1, width=2)

    if expression in (Expression.THINKING, Expression.ERROR):
        closed_eye(left_eye_x, eye_y, eye_radius)
        closed_eye(right_eye_x, eye_y, eye_radius)
    else:
        open_eye(left_eye_x, eye_y, eye_radius)
        open_eye(right_eye_x, eye_y, eye_radius)

    if expression == Expression.SPEAKING_HAPPY:
        draw.arc(
            (mouth_cx - mouth_half_width, mouth_y - 10, mouth_cx + mouth_half_width, mouth_y + 15),
            start=20, end=160, fill=1, width=2,
        )
    elif expression == Expression.SPEAKING_SAD:
        draw.arc(
            (mouth_cx - mouth_half_width, mouth_y, mouth_cx + mouth_half_width, mouth_y + 25),
            start=200, end=340, fill=1, width=2,
        )
    elif expression == Expression.SPEAKING_CONFUSED:
        draw.line(
            (mouth_cx - mouth_half_width, mouth_y, mouth_cx, mouth_y + 8, mouth_cx + mouth_half_width, mouth_y),
            fill=1, width=2,
        )
    elif expression == Expression.ERROR:
        draw.line((mouth_cx - mouth_half_width, mouth_y + 10, mouth_cx + mouth_half_width, mouth_y - 5), fill=1, width=2)
        draw.line((mouth_cx - mouth_half_width, mouth_y - 5, mouth_cx + mouth_half_width, mouth_y + 10), fill=1, width=2)
    elif expression == Expression.SETUP:
        draw.text((mouth_cx - 20, mouth_y - 5), "setup", fill=1)
    elif expression == Expression.LISTENING:
        # Small open ellipse mouth to suggest attentiveness
        mouth_ellipse_radius = max(2, height // 16)
        draw.ellipse(
            (mouth_cx - mouth_ellipse_radius, mouth_y - mouth_ellipse_radius, mouth_cx + mouth_ellipse_radius, mouth_y + mouth_ellipse_radius),
            outline=1, fill=0
        )
    elif expression == Expression.SPEAKING_NEUTRAL:
        # Double horizontal line to represent neutral speech
        draw.line((mouth_cx - mouth_half_width, mouth_y - 2, mouth_cx + mouth_half_width, mouth_y - 2), fill=1, width=2)
        draw.line((mouth_cx - mouth_half_width, mouth_y + 2, mouth_cx + mouth_half_width, mouth_y + 2), fill=1, width=2)
    else:
        # IDLE: single horizontal line
        draw.line((mouth_cx - mouth_half_width, mouth_y, mouth_cx + mouth_half_width, mouth_y), fill=1, width=2)

    return image


class FaceDisplay:
    def __init__(self, device: DisplayDevice) -> None:
        self._device = device

    def show(self, expression: Expression) -> None:
        image = render_expression(expression, (self._device.width, self._device.height))
        self._device.display(image)
