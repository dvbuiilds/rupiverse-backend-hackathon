from pathlib import Path

import pikepdf

from statement_parser.errors import StatementError


def decrypt_pdf(src: Path, dest_dir: Path, password: str | None) -> Path:
    """Write a decrypted copy of the PDF into dest_dir so every parser reads the same plain file."""
    dest = dest_dir / "decrypted.pdf"
    try:
        with pikepdf.open(src, password=password or "") as pdf:
            pdf.save(dest)
    except pikepdf.PasswordError as exc:
        if password:
            raise StatementError(422, "PDF_PASSWORD_INVALID", "The PDF password is incorrect.") from exc
        raise StatementError(422, "PDF_PASSWORD_REQUIRED", "This PDF is encrypted. Send its password.") from exc
    except pikepdf.PdfError as exc:
        raise StatementError(422, "PARSE_FAILED", "The PDF could not be opened. It may be damaged.") from exc
    return dest
