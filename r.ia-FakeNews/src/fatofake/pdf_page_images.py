"""Renderização segura de páginas de PDFs já armazenados pela aplicação."""

from __future__ import annotations

from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory


class PdfPageRenderingError(RuntimeError):
    pass


class PdfPageRenderer:
    def __init__(self, *, executable: str = "pdftoppm", timeout: float = 30.0) -> None:
        self.executable = executable
        self.timeout = timeout

    def render(self, content: bytes, page: int) -> bytes:
        if not content.startswith(b"%PDF"):
            raise PdfPageRenderingError("O arquivo original não é um PDF válido.")
        if not 1 <= page <= 100:
            raise PdfPageRenderingError("A página solicitada é inválida.")
        try:
            with TemporaryDirectory(prefix="artfact-pdf-") as temporary:
                source = Path(temporary) / "source.pdf"
                target = Path(temporary) / "page"
                source.write_bytes(content)
                subprocess.run(
                    [
                        self.executable,
                        "-f", str(page),
                        "-l", str(page),
                        "-singlefile",
                        "-jpeg",
                        "-jpegopt", "quality=82,optimize=y",
                        "-scale-to-x", "1200",
                        "-scale-to-y", "-1",
                        str(source),
                        str(target),
                    ],
                    check=True,
                    capture_output=True,
                    timeout=self.timeout,
                )
                image = target.with_suffix(".jpg")
                if not image.exists() or image.stat().st_size < 100:
                    raise PdfPageRenderingError("A página do PDF não pôde ser convertida em imagem.")
                return image.read_bytes()
        except PdfPageRenderingError:
            raise
        except (OSError, subprocess.SubprocessError) as error:
            raise PdfPageRenderingError("Não foi possível renderizar a página do PDF.") from error
