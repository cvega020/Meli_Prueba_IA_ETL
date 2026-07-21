"""Q&A generation package."""

from src.qa.qa_generator import DEFAULT_MODEL, RECOMMENDED_HEAVY_MODEL, QAGenerator, QAPair

__all__ = [
    "QAPair",
    "QAGenerator",
    "DEFAULT_MODEL",
    "RECOMMENDED_HEAVY_MODEL",
]
