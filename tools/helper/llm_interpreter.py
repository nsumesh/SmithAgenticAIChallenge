"""
LLM interpreter for compliance edge cases via Groq.

Standalone module used for borderline or conflicting-rule scenarios
where deterministic logic is insufficient.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Dict, List, Optional

from dotenv import load_dotenv
from groq import AsyncGroq

load_dotenv()

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a pharmaceutical regulatory compliance expert specialising in cold chain logistics.

Key principles:
1. Patient safety > cost savings
2. Biologics require stricter controls than standard refrigerated drugs
3. When in doubt, escalate to higher approval level
4. Always consider product stability data
5. Cite specific regulatory sections (EU GDP, FDA 21 CFR, WHO TRS 961, ICH)

Output format — valid JSON only:
{
  "compliance_decision": "compliant|violation|borderline",
  "reasoning": "2-3 sentence explanation with regulatory citations",
  "approval_level": "operator|qa_manager|director|none",
  "product_disposition": "release|quarantine|destroy|investigate",
  "additional_actions": ["action1", "action2"]
}"""


class ComplianceLLMInterpreter:

    def __init__(self):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY not found in environment")
        self.client = AsyncGroq(api_key=api_key)
        self.model = "llama-3.3-70b-versatile"

    async def interpret_edge_case(
        self,
        shipment_data: Dict,
        triggered_rules: List[Dict],
        rule_conflicts: Optional[List[str]] = None,
    ) -> Dict:
        prompt = self._build_prompt(shipment_data, triggered_rules, rule_conflicts)
        try:
            resp = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=1500,
                response_format={"type": "json_object"},
            )
            decision = json.loads(resp.choices[0].message.content)
            return {
                "llm_used": True,
                "llm_model": self.model,
                "compliance_decision": decision.get("compliance_decision"),
                "reasoning": decision.get("reasoning"),
                "recommended_approval_level": decision.get("approval_level"),
                "product_disposition": decision.get("product_disposition"),
                "additional_actions": decision.get("additional_actions", []),
            }
        except Exception as exc:
            logger.error("LLM interpreter failed: %s", exc)
            return {
                "llm_used": False,
                "error": str(exc),
                "fallback_decision": "CONSERVATIVE",
                "reasoning": "LLM failed, defaulting to strictest rule interpretation",
            }

    @staticmethod
    def _build_prompt(
        shipment_data: Dict,
        triggered_rules: List[Dict],
        rule_conflicts: Optional[List[str]],
    ) -> str:
        parts = [
            "COMPLIANCE EDGE CASE REVIEW\n",
            "SHIPMENT DETAILS:",
            f"- Shipment ID: {shipment_data.get('shipment_id')}",
            f"- Product Category: {shipment_data.get('product_category')}",
            f"- Current Temperature: {shipment_data.get('current_temp_c')}°C",
            f"- Minutes Outside Range: {shipment_data.get('minutes_outside_range')}",
            f"- Transit Phase: {shipment_data.get('transit_phase')}",
            "",
            "RISK ASSESSMENT (ML Model):",
            f"- Risk Score: {shipment_data.get('risk_score')}/100",
            f"- Spoilage Probability: {shipment_data.get('spoilage_probability', 0) * 100:.1f}%",
            "",
            f"RULES TRIGGERED:\n{json.dumps(triggered_rules, indent=2)}",
            "",
            f"FINANCIAL IMPACT:",
            f"- At-Risk Value: ${shipment_data.get('at_risk_value', 0):,.2f}",
            f"- Proposed Intervention Cost: ${shipment_data.get('proposed_intervention_cost', 0):,.2f}",
        ]
        if rule_conflicts:
            parts.append(f"\nRULE CONFLICTS DETECTED:\n{json.dumps(rule_conflicts, indent=2)}")
        parts.append(
            "\nProvide compliance decision, approval level, product disposition, "
            "and justification with regulatory citations. Respond ONLY with valid JSON."
        )
        return "\n".join(parts)
