"""Image upload utility: converts uploaded images to webp, stores with hash-based paths."""
import hashlib
import os

from PIL import Image
from flask import current_app


def save_uploaded_image(file_storage):
    """
    Process an uploaded image file:
    - Convert to WebP format
    - Fit to square ratio (center crop)
    - Store at data/uploads/images/<2char>/<4char>/<hash>.webp
    Returns the relative path for DB storage, or None on failure.
    """
    if not file_storage or not file_storage.filename:
        return None

    try:
        img = Image.open(file_storage.stream)
        img = img.convert("RGBA")

        # Center-crop to square
        w, h = img.size
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        img = img.crop((left, top, left + side, top + side))

        # Resize to reasonable max (512x512 for avatars/icons)
        if side > 512:
            img = img.resize((512, 512), Image.LANCZOS)

        # Convert to RGB for webp (drop alpha if no transparency)
        if not _has_transparency(img):
            img = img.convert("RGB")

        # Generate hash from pixel data
        pixel_hash = hashlib.sha256(img.tobytes()).hexdigest()

        # Build hash-based path: uploads/images/ab/abcd/<full_hash>.webp
        prefix_2 = pixel_hash[:2]
        prefix_4 = pixel_hash[:4]
        relative_dir = os.path.join("uploads", "images", prefix_2, prefix_4)
        filename = f"{pixel_hash}.webp"
        relative_path = os.path.join(relative_dir, filename)

        # Resolve absolute path under data/
        upload_root = os.path.join(current_app.instance_path, "..", "data")
        upload_root = os.path.abspath(upload_root)
        abs_dir = os.path.join(upload_root, relative_dir)
        os.makedirs(abs_dir, exist_ok=True)

        abs_path = os.path.join(abs_dir, filename)

        # Skip if already exists (deduplication via content hash)
        if not os.path.exists(abs_path):
            img.save(abs_path, "WEBP", quality=85)

        return relative_path

    except Exception:
        return None


def _has_transparency(img):
    """Check if an RGBA image has any transparent pixels."""
    if img.mode != "RGBA":
        return False
    extrema = img.getextrema()
    if len(extrema) >= 4:
        return extrema[3][0] < 255
    return False
