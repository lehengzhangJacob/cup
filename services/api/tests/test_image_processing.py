import io

import pytest
from PIL import Image

from app.image_processing import ImageValidationError, normalize_scenic_image


def _png(width=80, height=40):
    image = Image.new("RGBA", (width, height), (25, 100, 80, 160))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_normalize_image_converts_decodable_upload_to_jpeg():
    result = normalize_scenic_image(_png())

    assert result.mime_type == "image/jpeg"
    assert result.width == 80
    assert result.height == 40
    assert result.data[:2] == b"\xff\xd8"


def test_normalize_image_rejects_invalid_bytes():
    with pytest.raises(ImageValidationError):
        normalize_scenic_image(b"not-an-image")
