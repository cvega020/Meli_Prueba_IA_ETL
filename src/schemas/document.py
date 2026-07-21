"""Modelos Pydantic para documentos normalizados."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Document(BaseModel):
    """Documento normalizado como unidad canonica del pipeline.

    Cada registro conserva trazabilidad (`project_id`, `file_path`) y
    contiene un `id` deterministico generado desde el contenido limpio.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(..., min_length=1, description="Identificador deterministico basado en hash")
    project_id: str = Field(..., min_length=1, description="Identificador de proyecto desde ruta origen")
    file_path: str = Field(..., min_length=1, description="Ruta relativa desde docs_raw")
    content: str = Field(..., description="Contenido markdown normalizado")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Metadatos adicionales de origen y procesamiento",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Marca de tiempo UTC de procesamiento",
    )

    @field_validator("content")
    @classmethod
    def validate_content_not_empty(cls, value: str) -> str:
        """Validar que el contenido no sea vacio."""
        if not value.strip():
            raise ValueError("content no puede ser vacio o solo espacios")
        return value
