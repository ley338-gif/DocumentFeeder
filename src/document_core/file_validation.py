from pathlib import Path


class DocumentRejectedError(ValueError):
    status_code = 422


class FileTooLargeError(DocumentRejectedError):
    status_code = 413


class UnsupportedFileTypeError(DocumentRejectedError):
    status_code = 415


SUPPORTED_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".txt": "text/plain",
    ".csv": "text/plain",
    ".json": "text/plain",
    ".xml": "text/plain",
}


def detect_and_validate_type(path: Path, filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    expected = SUPPORTED_TYPES.get(suffix)
    if expected is None:
        raise UnsupportedFileTypeError(f"Dateityp {suffix or '(ohne Endung)'} wird nicht unterstützt")

    with path.open("rb") as source:
        sample = source.read(8192)
    if sample.startswith(b"%PDF-"):
        detected = "application/pdf"
    elif sample.startswith(b"\x89PNG\r\n\x1a\n"):
        detected = "image/png"
    elif sample.startswith(b"\xff\xd8\xff"):
        detected = "image/jpeg"
    elif sample.startswith((b"II*\x00", b"MM\x00*")):
        detected = "image/tiff"
    else:
        try:
            sample.decode("utf-8")
            detected = "text/plain"
        except UnicodeDecodeError as exc:
            raise UnsupportedFileTypeError(
                "Dateiinhalt entspricht keinem unterstützten Dateityp"
            ) from exc

    if detected != expected:
        raise UnsupportedFileTypeError(
            f"Dateiinhalt ({detected}) passt nicht zur Dateiendung {suffix}"
        )
    return detected
