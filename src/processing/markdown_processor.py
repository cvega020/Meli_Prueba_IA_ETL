"""Utilidades de ingesta y normalizacion de Markdown."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterator

import xxhash

from src.schemas.document import Document


class MarkdownProcessor:
    """Leer y normalizar archivos Markdown."""

    def __init__(self, docs_root: str | Path = "docs_raw") -> None:
        """Crear procesador para una raiz de documentos."""
        self.docs_root = Path(docs_root)
        self.logger = logging.getLogger(self.__class__.__name__)

    def iter_markdown_files(self) -> Iterator[Path]:
        """Iterar archivos Markdown recursivamente."""
        if not self.docs_root.exists():
            self.logger.warning("Carpeta de entrada no encontrada: %s", self.docs_root)
            return

        for path in sorted(self.docs_root.rglob("*.md")):
            if path.is_file():
                yield path

    @staticmethod
    def clean(content: str) -> str:
        """Limpiar texto Markdown."""
        cleaned = re.sub(r"<script\b[^>]*>.*?</script>", "", content, flags=re.IGNORECASE | re.DOTALL)
        cleaned = re.sub(r"<!--.*?-->", "", cleaned, flags=re.DOTALL)
        cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        cleaned = "\n".join(line.strip() for line in cleaned.split("\n"))
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    @staticmethod
    def generate_hash(content: str) -> str:
        """Generar hash deterministico del contenido."""
        return xxhash.xxh3_128_hexdigest(content.encode("utf-8"))

    def process_file(self, file_path: str | Path) -> Document:
        """Procesar un archivo Markdown."""
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Archivo Markdown no encontrado: {path}")

        content = self.clean(path.read_text(encoding="utf-8", errors="ignore"))

        if self.docs_root in path.parents:
            rel = path.relative_to(self.docs_root)
            project_id = rel.parts[0] if len(rel.parts) > 1 else "default_project"
            file_path_str = rel.as_posix()
        else:
            project_id = path.parent.name or "default_project"
            file_path_str = path.as_posix()

        metadata = {
            "source_file_name": path.name,
            "source_extension": path.suffix.lower(),
            "char_count": len(content),
        }

        return Document(
            id=self.generate_hash(content),
            project_id=project_id,
            file_path=file_path_str,
            content=content,
            metadata=metadata,
        )

    def process_all(self) -> list[Document]:
        """Procesar todos los archivos Markdown."""
        docs: list[Document] = []
        for path in self.iter_markdown_files():
            docs.append(self.process_file(path))
        self.logger.info("Ingesta completada | documentos=%s", len(docs))
        return docs
