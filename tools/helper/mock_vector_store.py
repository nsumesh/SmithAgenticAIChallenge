"""
Mock vector store for fallback when Supabase pgvector is unavailable.

Returns hardcoded pharmaceutical cold-chain regulations so the compliance
agent can still produce meaningful results without a live database.
"""
from __future__ import annotations

from typing import Dict, List, Optional

_MOCK_REGULATIONS: List[Dict] = [
    {
        "regulation_id": "FDA-CFR-211.142",
        "regulation_name": "Temperature Control Requirements",
        "authority": "FDA",
        "section": "21 CFR 211.142",
        "title": "Temperature Control Requirements",
        "content": (
            "Pharmaceutical products must be stored and transported within "
            "specified temperature ranges. Warehousing procedures shall include "
            "a system for rotating stock and a system for segregating rejected "
            "drug products. Products requiring controlled temperature storage "
            "must be maintained under prescribed conditions during distribution."
        ),
        "metadata": {"url": "https://www.fda.gov"},
    },
    {
        "regulation_id": "EU-GDP-9.2",
        "regulation_name": "EU GDP Temperature Monitoring",
        "authority": "EU",
        "section": "GDP 9.2",
        "title": "EU GDP Temperature Monitoring",
        "content": (
            "Temperature mapping and monitoring of storage and transport "
            "conditions. Any deviations from specified storage conditions "
            "must be documented and investigated. Corrective and preventive "
            "actions should be taken. Temperature excursions must be reported "
            "and the impact on product quality assessed."
        ),
        "metadata": {"url": "https://ec.europa.eu"},
    },
    {
        "regulation_id": "ICH-Q1A",
        "regulation_name": "ICH Q1A(R2) Stability Testing",
        "authority": "ICH",
        "section": "Q1A(R2)",
        "title": "Stability Testing Guidelines",
        "content": (
            "Stability testing provides evidence on how pharmaceutical "
            "quality varies with time under the influence of environmental "
            "factors such as temperature, humidity, and light exposure. "
            "Temperature excursions during transport must be evaluated "
            "against stability data to determine product acceptability."
        ),
        "metadata": {"url": "https://www.ich.org"},
    },
    {
        "regulation_id": "WHO-TRS961-ANNEX9",
        "regulation_name": "WHO Model Guidance for Storage and Transport",
        "authority": "WHO",
        "section": "TRS 961 Annex 9",
        "title": "WHO Storage and Transport Guidance",
        "content": (
            "Products requiring cold chain must not be subjected to "
            "freezing unless specified. Biologics exposed to temperatures "
            "outside 2-8°C for cumulative periods exceeding 60 minutes "
            "require quality assessment. Products should be quarantined "
            "until disposition is determined by qualified person."
        ),
        "metadata": {"url": "https://www.who.int"},
    },
    {
        "regulation_id": "FDA-CFR-600.15",
        "regulation_name": "Biologics Temperature Requirements",
        "authority": "FDA",
        "section": "21 CFR 600.15",
        "title": "Biologics Temperature Requirements",
        "content": (
            "Biological products require strict temperature control at all "
            "times during manufacture, storage, and distribution. Each "
            "product shall be maintained at the temperature specified in "
            "applicable standards. Deviation requires investigation and "
            "qualified person sign-off before release."
        ),
        "metadata": {"url": "https://www.fda.gov"},
    },
    {
        "regulation_id": "FDA-21CFR11",
        "regulation_name": "FDA 21 CFR Part 11 - Electronic Records",
        "authority": "FDA",
        "section": "21 CFR Part 11",
        "title": "Electronic Records and Signatures",
        "content": (
            "Electronic records used in compliance must be trustworthy, "
            "reliable, and equivalent to paper records. Audit trails must "
            "be computer-generated, time-stamped, and append-only. Access "
            "controls and authority checks are required."
        ),
        "metadata": {"url": "https://www.fda.gov"},
    },
]


class MockComplianceVectorStore:
    """In-memory regulation store that mimics the pgvector search interface."""

    def __init__(self):
        self._docs = list(_MOCK_REGULATIONS)

    def add_documents(self, chunks: List[Dict]) -> int:
        self._docs.extend(chunks)
        return len(chunks)

    def search(
        self,
        query: str,
        limit: int = 5,
        similarity_threshold: float = 0.3,
    ) -> List[Dict]:
        query_lower = query.lower()
        scored = []
        for doc in self._docs:
            text = f"{doc.get('content', '')} {doc.get('regulation_name', '')}".lower()
            overlap = sum(1 for w in query_lower.split() if w in text)
            score = overlap / max(len(query_lower.split()), 1)
            if score >= similarity_threshold:
                scored.append({**doc, "similarity": round(score, 3)})
        scored.sort(key=lambda d: d["similarity"], reverse=True)
        return scored[:limit]

    def count_documents(self) -> int:
        return len(self._docs)
