"""
RAG-powered Compliance Agent — validates pharmaceutical shipments against
FDA, EU GDP, WHO, and ICH regulations using semantic search + LLM.

Architecture:
  1. Audit log (immutable JSONL append — always succeeds)
  2. Semantic search over regulatory vector store (Supabase pgvector)
  3. LLM interpretation via Groq (llama-3.3-70b-versatile)
  4. Structured output: compliance status, violations, disposition, citations

Falls back gracefully:
  - Vector store unavailable → hardcoded mock regulations
  - LLM unavailable → conservative deterministic decision
  - Both unavailable → audit-only mode (still logs)
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

load_dotenv()

logger = logging.getLogger(__name__)

LOG_DIR = Path(__file__).resolve().parent.parent / "audit_logs"

# ---------------------------------------------------------------------------
# RAG Compliance Agent core
# ---------------------------------------------------------------------------

class VectorComplianceAgent:
    """
    Vector-based compliance agent: semantic search + LLM interpretation.

    Workflow:
      1. Build search query from shipment context
      2. Retrieve relevant regulations from vector store
      3. LLM interprets regulations → compliance decision
      4. Return structured output
    """

    def __init__(self):
        try:
            from tools.helper.vector_store import ComplianceVectorStore

            self.vector_store = ComplianceVectorStore()
            doc_count = self.vector_store.count_documents()
            self.vector_enabled = True
            logger.info("Compliance vector store ready (%d docs)", doc_count)
        except Exception as exc:
            logger.warning("Vector store init failed: %s — fallback mode", exc)
            self.vector_store = None
            self.vector_enabled = False

        api_key = os.getenv("GROQ_API_KEY")
        if api_key:
            try:
                from groq import AsyncGroq

                self.llm = AsyncGroq(api_key=api_key)
                self.model = "llama-3.3-70b-versatile"
                self.llm_enabled = True
                logger.info("Compliance LLM ready (Groq %s)", self.model)
            except Exception as exc:
                logger.warning("Groq init failed: %s — deterministic fallback", exc)
                self.llm = None
                self.llm_enabled = False
        else:
            logger.info("GROQ_API_KEY not set — compliance LLM disabled")
            self.llm = None
            self.llm_enabled = False

        self.version = "2.0.0-rag"

    # ── main entry ────────────────────────────────────────────────────
    async def validate_compliance(
        self,
        shipment_id: str,
        container_id: str,
        window_id: str,
        event_type: str,
        risk_tier: str,
        details: Dict[str, Any],
        regulatory_tags: Optional[List[str]] = None,
    ) -> Dict:
        start = datetime.utcnow()

        state = self._build_state(
            shipment_id, container_id, window_id,
            event_type, risk_tier, details, regulatory_tags,
        )

        query = self._build_search_query(state)
        logger.info("Compliance search: %s", query[:120])

        if self.vector_enabled:
            regs = self.vector_store.search(query=query, limit=5, similarity_threshold=0.3)
            logger.info("Vector search returned %d regulations", len(regs))
        else:
            regs = self._fallback_regulations(state)
            logger.info("Using %d fallback regulations", len(regs))

        if self.llm_enabled:
            decision = await self._llm_interpret(state, regs)
        else:
            decision = self._deterministic_decision(state)

        output = self._build_output(state, regs, decision)
        output["validation_duration_ms"] = int(
            (datetime.utcnow() - start).total_seconds() * 1000
        )

        logger.info(
            "Compliance decision: %s (method=%s, %dms)",
            output["compliance_status"],
            output["decision_method"],
            output["validation_duration_ms"],
        )
        return output

    # ── state builder ────────────────────────────────────────────────
    @staticmethod
    def _build_state(
        shipment_id, container_id, window_id,
        event_type, risk_tier, details, regulatory_tags,
    ) -> Dict:
        product_category = details.get(
            "product_category",
            details.get("product_type", "standard_refrigerated"),
        )
        current_temp_c = float(
            details.get("current_temp_c", details.get("temperature", details.get("avg_temp_c", 0.0)))
        )
        minutes_outside_range = int(
            details.get("minutes_outside_range", details.get("duration_minutes", details.get("excursion_duration", 0)))
        )
        transit_phase = details.get("transit_phase", details.get("phase", "unknown"))
        spoilage_prob = float(
            details.get("spoilage_probability", details.get("ml_prob", 0.0))
        )
        at_risk_value = float(details.get("at_risk_value", details.get("estimated_loss", 0.0)))

        risk_map = {"LOW": 25, "MEDIUM": 50, "HIGH": 75, "CRITICAL": 95}
        risk_score = risk_map.get(risk_tier.upper(), 50)

        return {
            "shipment_id": shipment_id,
            "container_id": container_id,
            "window_id": window_id,
            "event_type": event_type,
            "product_category": product_category,
            "current_temp_c": current_temp_c,
            "minutes_outside_range": minutes_outside_range,
            "transit_phase": transit_phase,
            "risk_score": risk_score,
            "risk_tier": risk_tier,
            "spoilage_probability": spoilage_prob,
            "at_risk_value": at_risk_value,
            "critical_patients_affected": int(details.get("critical_patients_affected", 0)),
            "affected_facilities": details.get("affected_facilities", []),
            "regulatory_tags": regulatory_tags or [],
        }

    # ── search query ─────────────────────────────────────────────────
    @staticmethod
    def _build_search_query(state: Dict) -> str:
        return (
            f"{state['product_category']} pharmaceutical product "
            f"temperature excursion {state['minutes_outside_range']} minutes "
            f"risk score {state['risk_score']} "
            f"regulatory requirements approval deviation report"
        )

    # ── fallback regs ────────────────────────────────────────────────
    @staticmethod
    def _fallback_regulations(state: Dict) -> List[Dict]:
        regs = [
            {
                "regulation_id": "FDA-CFR-211.142",
                "regulation_name": "Temperature Control Requirements",
                "authority": "FDA",
                "section": "21 CFR 211.142",
                "similarity": 0.85,
                "content": "Pharmaceutical products must be stored and transported within specified temperature ranges.",
                "metadata": {"url": "https://www.fda.gov"},
            },
            {
                "regulation_id": "ICH-Q1A",
                "regulation_name": "Stability Testing Guidelines",
                "authority": "ICH",
                "section": "Q1A(R2)",
                "similarity": 0.78,
                "content": "Stability testing provides evidence on how pharmaceutical quality varies with environmental factors.",
                "metadata": {"url": "https://www.ich.org"},
            },
        ]
        if state["product_category"] in ("biologics", "vaccines"):
            regs.append(
                {
                    "regulation_id": "FDA-CFR-600.15",
                    "regulation_name": "Biologics Temperature Requirements",
                    "authority": "FDA",
                    "section": "21 CFR 600.15",
                    "similarity": 0.92,
                    "content": "Biological products require strict temperature control.",
                    "metadata": {"url": "https://www.fda.gov"},
                }
            )
        return regs

    # ── LLM interpret ────────────────────────────────────────────────
    async def _llm_interpret(self, state: Dict, regs: List[Dict]) -> Dict:
        reg_ctx = "\n".join(
            f"REGULATION {i+1}: {r.get('regulation_id', '?')} - "
            f"{r.get('regulation_name', '?')}\n{str(r.get('content', ''))[:400]}"
            for i, r in enumerate(regs)
        )
        prompt = f"""\
SHIPMENT CONTEXT:
- ID: {state['shipment_id']} | Container: {state['container_id']}
- Product: {state['product_category']}
- Temperature: {state['current_temp_c']}°C for {state['minutes_outside_range']} min outside range
- Transit Phase: {state['transit_phase']}
- Risk: {state['risk_tier']} ({state['risk_score']}/100)
- Spoilage Prob: {state['spoilage_probability']*100:.1f}%
- Value at risk: ${state['at_risk_value']:,.0f}

REGULATIONS:
{reg_ctx}

Return compliance assessment as JSON:
{{"compliance_decision":"compliant|violation|borderline","severity":"minor|major|critical",\
"human_approval_required":true|false,"approval_level":"operator|qa_manager|director|none",\
"product_disposition":"release|quarantine|destroy|investigate",\
"deviation_report_required":true|false,"reasoning":"brief explanation with citations",\
"violated_regulations":["REG-ID"],"required_actions":["action"]}}"""

        try:
            resp = await self.llm.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a pharmaceutical regulatory expert. Respond only with valid JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=1500,
                response_format={"type": "json_object"},
            )
            return json.loads(resp.choices[0].message.content)
        except Exception as exc:
            logger.error("LLM compliance interpretation failed: %s", exc)
            return self._deterministic_decision(state)

    # ── deterministic fallback ───────────────────────────────────────
    @staticmethod
    def _deterministic_decision(state: Dict) -> Dict:
        tier = state["risk_tier"].upper()
        if tier == "CRITICAL":
            return {
                "compliance_decision": "violation",
                "severity": "critical",
                "human_approval_required": True,
                "approval_level": "director",
                "product_disposition": "quarantine",
                "deviation_report_required": True,
                "reasoning": "CRITICAL risk tier — conservative deterministic ruling (LLM unavailable)",
                "violated_regulations": [],
                "required_actions": ["Immediate quarantine", "QA director review"],
            }
        if tier == "HIGH":
            return {
                "compliance_decision": "violation",
                "severity": "major",
                "human_approval_required": True,
                "approval_level": "qa_manager",
                "product_disposition": "quarantine",
                "deviation_report_required": True,
                "reasoning": "HIGH risk tier — conservative deterministic ruling (LLM unavailable)",
                "violated_regulations": [],
                "required_actions": ["QA manager review", "Deviation report within 24h"],
            }
        if tier == "MEDIUM":
            return {
                "compliance_decision": "borderline",
                "severity": "minor",
                "human_approval_required": False,
                "approval_level": "none",
                "product_disposition": "investigate",
                "deviation_report_required": False,
                "reasoning": "MEDIUM risk — monitoring recommended",
                "violated_regulations": [],
                "required_actions": ["Continue monitoring"],
            }
        return {
            "compliance_decision": "compliant",
            "severity": "minor",
            "human_approval_required": False,
            "approval_level": "none",
            "product_disposition": "release",
            "deviation_report_required": False,
            "reasoning": "LOW risk — within acceptable limits",
            "violated_regulations": [],
            "required_actions": [],
        }

    # ── output builder ───────────────────────────────────────────────
    def _build_output(
        self, state: Dict, regs: List[Dict], decision: Dict
    ) -> Dict:
        violations = []
        if decision.get("compliance_decision") == "violation":
            for reg_id in decision.get("violated_regulations", []):
                violations.append(
                    {
                        "violation_type": reg_id,
                        "severity": decision.get("severity", "MAJOR").upper(),
                        "regulation": reg_id,
                        "description": f"Violation of {reg_id}",
                        "action_required": ", ".join(decision.get("required_actions", [])),
                    }
                )

        regs_checked = list(
            {f"{r.get('authority', '?')} - {r.get('regulation_name', '?')}" for r in regs}
        )

        method = "vector_search_llm" if self.llm_enabled else "deterministic_fallback"
        if not self.vector_enabled:
            method = f"mock_regs_{method}"

        return {
            "shipment_id": state["shipment_id"],
            "container_id": state["container_id"],
            "window_id": state["window_id"],
            "event_type": state["event_type"],
            "risk_tier": state["risk_tier"],
            "regulatory_tags": state["regulatory_tags"],
            "compliance_status": decision.get("compliance_decision", "violation"),
            "compliance_score": 100 if decision.get("compliance_decision") == "compliant" else 50,
            "regulations_checked": regs_checked,
            "violations": violations,
            "warnings": [],
            "human_approval_required": decision.get("human_approval_required", True),
            "approval_reason": decision.get("reasoning"),
            "approval_level": decision.get("approval_level", "qa_manager"),
            "approval_urgency": (
                "immediate" if decision.get("approval_level") == "director" else "within_24h"
            ),
            "product_disposition": decision.get("product_disposition", "quarantine"),
            "disposition_justification": decision.get("reasoning"),
            "deviation_report_required": decision.get("deviation_report_required", False),
            "audit_trail_generated": True,
            "audit_record_id": f"AUDIT-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            "applicable_citations": [
                {
                    "regulation": r.get("regulation_id", ""),
                    "title": r.get("regulation_name", ""),
                    "url": (r.get("metadata") or {}).get("url"),
                    "similarity": r.get("similarity"),
                }
                for r in regs
            ],
            "decision_method": method,
            "validated_at": datetime.utcnow().isoformat(),
            "agent_version": self.version,
        }


# ---------------------------------------------------------------------------
# Singleton & async-safe runner
# ---------------------------------------------------------------------------

_compliance_agent: Optional[VectorComplianceAgent] = None


def _get_agent() -> VectorComplianceAgent:
    global _compliance_agent
    if _compliance_agent is None:
        _compliance_agent = VectorComplianceAgent()
    return _compliance_agent


def _run_async(coro):
    """Run an async coroutine from sync context, even inside a running event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=30)


# ---------------------------------------------------------------------------
# LangChain tool wrapper
# ---------------------------------------------------------------------------

class ComplianceInput(BaseModel):
    shipment_id: str
    container_id: str
    window_id: str
    event_type: str = Field(
        description="Type: risk_assessment, excursion, action_taken, approval_decision",
    )
    risk_tier: str = Field(description="Risk tier: LOW, MEDIUM, HIGH, CRITICAL")
    details: Dict[str, Any] = Field(description="Event-specific payload")
    regulatory_tags: List[str] = Field(
        default_factory=list,
        description="Applicable tags: GDP, FDA_21CFR11, WHO_PQS, DSCSA",
    )


def _execute(
    shipment_id: str,
    container_id: str,
    window_id: str,
    event_type: str,
    risk_tier: str,
    details: Dict[str, Any],
    regulatory_tags: List[str] | None = None,
) -> dict:
    """
    1. Append immutable audit record (always succeeds)
    2. Run RAG compliance validation (vector search + LLM)
    3. Return combined result
    """
    # ── 1. AUDIT LOG ──
    log_id = f"CL-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
    timestamp = datetime.now(timezone.utc).isoformat()
    audit_record = {
        "log_id": log_id,
        "timestamp": timestamp,
        "shipment_id": shipment_id,
        "container_id": container_id,
        "window_id": window_id,
        "event_type": event_type,
        "risk_tier": risk_tier,
        "details": details,
        "regulatory_tags": regulatory_tags or [],
        "immutable": True,
    }
    LOG_DIR.mkdir(exist_ok=True)
    log_path = LOG_DIR / "compliance_events.jsonl"
    with open(log_path, "a") as f:
        f.write(json.dumps(audit_record) + "\n")

    # ── 2. RAG VALIDATION ──
    compliance_result = None
    compliance_error = None
    try:
        agent = _get_agent()
        compliance_result = _run_async(
            agent.validate_compliance(
                shipment_id=shipment_id,
                container_id=container_id,
                window_id=window_id,
                event_type=event_type,
                risk_tier=risk_tier,
                details=details,
                regulatory_tags=regulatory_tags or [],
            )
        )
    except Exception as exc:
        compliance_error = str(exc)
        logger.error("Compliance validation failed: %s", exc)

    # ── 3. COMBINED RESULT ──
    result: Dict[str, Any] = {
        "tool": "compliance_agent",
        "status": "completed" if compliance_result else "audit_only",
        "log_id": log_id,
        "log_path": str(log_path),
        "timestamp": timestamp,
    }

    if compliance_result:
        result.update(
            {
                "compliance_validation": compliance_result,
                "compliance_status": compliance_result.get("compliance_status"),
                "human_approval_required": compliance_result.get("human_approval_required"),
                "product_disposition": compliance_result.get("product_disposition"),
                "violations": compliance_result.get("violations", []),
                "regulations_checked": compliance_result.get("regulations_checked", []),
                "decision_method": compliance_result.get("decision_method", "unknown"),
            }
        )
    else:
        result.update(
            {
                "compliance_validation": None,
                "compliance_error": compliance_error,
                "compliance_status": "audit_only",
                "human_approval_required": True,
                "product_disposition": "quarantine",
            }
        )

    return result


compliance_tool = StructuredTool.from_function(
    func=_execute,
    name="compliance_agent",
    description=(
        "Validate pharmaceutical shipment compliance using AI-powered regulatory analysis. "
        "Performs semantic search over FDA, EU GDP, WHO, ICH regulations and uses LLM "
        "to interpret requirements. Returns compliance status, violations, approvals needed, "
        "and product disposition. Includes immutable audit logging."
    ),
    args_schema=ComplianceInput,
)
