"""
Parse compliance PDF documents into chunks for vectorisation.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict, List

from pypdf import PdfReader

logger = logging.getLogger(__name__)


class ComplianceDocumentParser:

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def parse_pdf(self, pdf_path: str, metadata: Dict) -> List[Dict]:
        logger.info("Parsing PDF %s …", pdf_path)
        reader = PdfReader(pdf_path)
        full_text = ""
        for page_num, page in enumerate(reader.pages):
            full_text += f"\n[Page {page_num + 1}]\n{page.extract_text()}"

        full_text = self._clean_text(full_text)
        sections = self._split_into_sections(full_text, metadata)

        chunks: List[Dict] = []
        for section in sections:
            chunks.extend(self._chunk_text(section["content"], section))

        logger.info("Created %d chunks from %d pages", len(chunks), len(reader.pages))
        return chunks

    @staticmethod
    def _clean_text(text: str) -> str:
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r" {2,}", " ", text)
        text = re.sub(r"^\d+\s*$", "", text, flags=re.MULTILINE)
        return text.strip()

    @staticmethod
    def _split_into_sections(text: str, metadata: Dict) -> List[Dict]:
        patterns = [
            r"(?:Section|SECTION)\s+(\d+(?:\.\d+)*)\s*[:\-]?\s*(.+)",
            r"(\d+(?:\.\d+)+)\s+(.+)",
            r"([A-Z][A-Z\s]{3,})",
        ]
        sections: List[Dict] = []
        current_section = None
        current_content: List[str] = []

        for line in text.split("\n"):
            is_header = False
            for pattern in patterns:
                match = re.match(pattern, line.strip())
                if match:
                    if current_section:
                        sections.append(
                            {
                                "regulation_id": metadata.get("regulation_id"),
                                "section": current_section,
                                "title": current_section,
                                "content": "\n".join(current_content).strip(),
                                "metadata": metadata,
                            }
                        )
                    if len(match.groups()) >= 2:
                        current_section = f"{match.group(1)} - {match.group(2)}"
                    else:
                        current_section = match.group(1)
                    current_content = []
                    is_header = True
                    break
            if not is_header:
                current_content.append(line)

        if current_section and current_content:
            sections.append(
                {
                    "regulation_id": metadata.get("regulation_id"),
                    "section": current_section,
                    "title": current_section,
                    "content": "\n".join(current_content).strip(),
                    "metadata": metadata,
                }
            )

        if not sections:
            sections = [
                {
                    "regulation_id": metadata.get("regulation_id"),
                    "section": "Full Document",
                    "title": metadata.get("regulation_name", "Unknown"),
                    "content": text,
                    "metadata": metadata,
                }
            ]
        return sections

    def _chunk_text(self, text: str, section_metadata: Dict) -> List[Dict]:
        chunks: List[Dict] = []
        words = text.split()
        step = max(1, self.chunk_size - self.chunk_overlap)
        for i in range(0, len(words), step):
            chunk_text = " ".join(words[i : i + self.chunk_size])
            if len(chunk_text.strip()) < 50:
                continue
            chunks.append(
                {
                    "regulation_id": section_metadata["regulation_id"],
                    "section": section_metadata["section"],
                    "title": section_metadata["title"],
                    "content": chunk_text,
                    "metadata": section_metadata["metadata"],
                    "chunk_index": len(chunks),
                }
            )
        return chunks
