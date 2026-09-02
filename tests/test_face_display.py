from haro.face_display import (
    Expression,
    FaceDisplay,
    expression_for_emotion,
    render_expression,
)


def test_expression_for_emotion_known_values():
    assert expression_for_emotion("happy") == Expression.SPEAKING_HAPPY
    assert expression_for_emotion("sad") == Expression.SPEAKING_SAD
    assert expression_for_emotion("confused") == Expression.SPEAKING_CONFUSED
    assert expression_for_emotion("neutral") == Expression.SPEAKING_NEUTRAL


def test_expression_for_emotion_unknown_defaults_to_neutral():
    assert expression_for_emotion("bewildered") == Expression.SPEAKING_NEUTRAL


def test_render_expression_returns_correct_size():
    image = render_expression(Expression.IDLE, size=(128, 64))
    assert image.size == (128, 64)


def test_render_expression_differs_between_expressions():
    idle = render_expression(Expression.IDLE, size=(128, 64))
    happy = render_expression(Expression.SPEAKING_HAPPY, size=(128, 64))
    sad = render_expression(Expression.SPEAKING_SAD, size=(128, 64))
    assert idle.tobytes() != happy.tobytes()
    assert happy.tobytes() != sad.tobytes()


class FakeDevice:
    def __init__(self, width: int = 128, height: int = 64) -> None:
        self.width = width
        self.height = height
        self.displayed = []

    def display(self, image) -> None:
        self.displayed.append(image)


def test_face_display_show_renders_to_device():
    device = FakeDevice()
    face = FaceDisplay(device)

    face.show(Expression.LISTENING)

    assert len(device.displayed) == 1
    assert device.displayed[0].size == (128, 64)
