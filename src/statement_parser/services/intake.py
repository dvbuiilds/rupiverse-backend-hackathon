import hashlib
from pathlib import Path

from fastapi import UploadFile

from statement_parser.errors import StatementError

CHUNK_SIZE = 1024 * 1024
PDF_SIGNATURE = b"%PDF-"


def save_upload(upload: UploadFile, dest_dir: Path, max_mb: int) -> tuple[Path, str]:
    """Stream the upload to disk, enforcing the size cap and PDF signature. Returns (path, sha256)."""
    max_bytes = max_mb * 1024 * 1024
    dest = dest_dir / "original.pdf"
    digest = hashlib.sha256()
    size = 0

    with dest.open("wb") as out:
        while chunk := upload.file.read(CHUNK_SIZE):
            if size == 0 and not chunk.startswith(PDF_SIGNATURE):
                raise StatementError(415, "NOT_A_PDF", "The uploaded file is not a PDF.")
            size += len(chunk)
            if size > max_bytes:
                raise StatementError(413, "FILE_TOO_LARGE", f"PDF is larger than {max_mb} MB.")
            digest.update(chunk)
            out.write(chunk)

    if size == 0:
        raise StatementError(415, "NOT_A_PDF", "The uploaded file is empty.")
    return dest, digest.hexdigest()
