"""Image processing utilities."""


def detect_mime_type(image_bytes: bytes) -> str:
    """Detect image MIME type from magic bytes.

    Supports common formats including both OpenAI-supported formats
    (PNG, JPEG, WebP, GIF) and unsupported formats (TIFF, BMP, JPEG2000)
    for better error messages.

    Args:
        image_bytes: Raw image bytes

    Returns:
        MIME type string (e.g., "image/png")
    """
    if len(image_bytes) < 12:
        return "application/octet-stream"

    # Magic byte signatures for different image formats
    mime_types = [
        (b"\x89PNG\r\n\x1a\n", 0, 8, "image/png"),
        (b"\xff\xd8\xff", 0, 3, "image/jpeg"),
        ((b"GIF87a", b"GIF89a"), 0, 6, "image/gif"),
        (b"BM", 0, 2, "image/bmp"),
        ((b"II\x2a\x00", b"MM\x00\x2a"), 0, 4, "image/tiff"),
        (b"\x00\x00\x01\x00", 0, 4, "image/x-icon"),
    ]

    for pattern, offset, length, mime in mime_types:
        data = image_bytes[offset : offset + length]
        if isinstance(pattern, tuple):
            if data in pattern:
                return mime
        elif data == pattern:
            return mime

    # WebP requires checking two separate regions
    if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"

    # JPEG2000 has specific signature
    if image_bytes[:4] == b"\x00\x00\x00\x0c" and image_bytes[4:8] == b"jP  ":
        return "image/jp2"

    return "application/octet-stream"


def detect_mime_type_with_extension(image_bytes: bytes) -> tuple[str, str]:
    """Detect image MIME type and file extension from magic bytes.

    Args:
        image_bytes: Raw image bytes

    Returns:
        Tuple of (mime_type, extension), e.g., ("image/png", "png")
    """
    mime_type = detect_mime_type(image_bytes)

    # Map MIME types to extensions
    extensions = {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/gif": "gif",
        "image/webp": "webp",
        "image/bmp": "bmp",
        "image/tiff": "tiff",
        "image/x-icon": "ico",
        "image/jp2": "jp2",
    }

    extension = extensions.get(mime_type, "jpg")
    return mime_type, extension


def strip_data_url_prefix(base64_data: str) -> str:
    """Strip data URL prefix from base64 string if present.

    Mistral OCR returns base64 data with format: data:image/jpeg;base64,/9j/4AAQ...
    This strips the prefix to get just the base64 content.

    Args:
        base64_data: Base64 string, possibly with data URL prefix

    Returns:
        Pure base64 string without prefix
    """
    if base64_data.startswith("data:"):
        # Format: data:image/jpeg;base64,/9j/4AAQ...
        return base64_data.split(",", 1)[1]
    return base64_data


def get_image_dimensions(image_bytes: bytes) -> tuple[int | None, int | None]:
    """Extract image dimensions from bytes.

    Args:
        image_bytes: Raw image bytes

    Returns:
        Tuple of (width, height), or (None, None) if unable to determine
    """
    import io

    from PIL import Image

    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            return img.width, img.height
    except Exception:
        return None, None
