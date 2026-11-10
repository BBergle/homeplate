import io
import os
import uuid
import warnings

import pillow_heif
from PIL import Image, ImageOps

pillow_heif.register_heif_opener()

MAX_BYTES = 15 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 50_000_000


def photos_dir() -> str:
    return os.path.join(os.environ.get("DATA_DIR", "/data"), "photos")


def save(upload_bytes: bytes) -> str:
    if len(upload_bytes) > MAX_BYTES:
        raise ValueError("too large")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)  # warning range is an error too
            src = Image.open(io.BytesIO(upload_bytes), formats=["JPEG", "PNG", "WEBP", "HEIF", "MPO"])
            icc = src.info.get("icc_profile")
            img = ImageOps.exif_transpose(src).convert("RGB")
    except Exception as e:
        raise ValueError("not an image") from e
    img.thumbnail((1600, 1600))
    os.makedirs(photos_dir(), exist_ok=True)
    name = f"{uuid.uuid4()}.jpg"
    img.save(os.path.join(photos_dir(), name), "JPEG", quality=85, icc_profile=icc)  # new image: no EXIF carried over
    return name
