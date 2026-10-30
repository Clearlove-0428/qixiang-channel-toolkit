"""Bounded local JPEG archive: one file per compressed content hash."""
from __future__ import annotations
import hashlib
import io
import warnings
from pathlib import Path
from PIL import Image, ImageOps

MAX_SAVED_BYTES = 1_000_000
Image.MAX_IMAGE_PIXELS = 64_000_000


def compress_image(payload: bytes, max_bytes=950_000, max_edge=4096) -> tuple[bytes, dict]:
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(payload)) as opened:
            animated = bool(getattr(opened, 'is_animated', False))
            opened.seek(0)
            image = ImageOps.exif_transpose(opened).convert('RGBA')
            background = Image.new('RGBA', image.size, 'white')
            background.alpha_composite(image)
            image = background.convert('RGB')
    original = image.size
    image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    while True:
        for quality in (85, 75, 65, 55):
            output = io.BytesIO()
            image.save(output, format='JPEG', quality=quality, optimize=True)
            compressed = output.getvalue()
            if len(compressed) <= max_bytes:
                return compressed, {'width': image.width, 'height': image.height,
                    'original_width': original[0], 'original_height': original[1],
                    'quality': quality, 'animated_first_frame': animated}
        image = image.resize((max(1, int(image.width * .8)), max(1, int(image.height * .8))), Image.Resampling.LANCZOS)


def store_image(payload: bytes, folder: Path, max_bytes=950_000, max_edge=4096) -> dict:
    compressed, info = compress_image(payload, min(max_bytes,950_000), max_edge)
    if len(compressed) > MAX_SAVED_BYTES:
        raise ValueError('compressed_image_exceeds_limit')
    digest = hashlib.sha256(compressed).hexdigest()
    name = digest + '.jpg'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    if not target.exists():
        temporary = target.with_suffix('.tmp')
        temporary.write_bytes(compressed)
        temporary.replace(target)
    return dict(info, relative_path=name, sha256=digest, bytes=len(compressed))
