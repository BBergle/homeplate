import io
import os
import uuid

import pillow_heif
from PIL import Image, ImageOps

pillow_heif.register_heif_opener()

MAX_BYTES = 15 * 1024 * 1024


def photos_dir() -> str:
    return os.path.join(os.environ.get("DATA_DIR", "/data"), "photos")


def save(upload_bytes: bytes) -> str:
    if len(upload_bytes) > MAX_BYTES:
        raise ValueError("too large")
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(upload_bytes), formats=["JPEG", "PNG", "WEBP", "HEIF", "MPO"])).convert("RGB")
    except Exception as e:
        raise ValueError("not an image") from e
    img.thumbnail((1600, 1600))
    os.makedirs(photos_dir(), exist_ok=True)
    name = f"{uuid.uuid4()}.jpg"
    img.save(os.path.join(photos_dir(), name), "JPEG", quality=85)  # new image: no EXIF carried over
    return name
