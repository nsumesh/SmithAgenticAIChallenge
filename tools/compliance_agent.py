"""
Unified Compliance Agent
Combines vector-based compliance validation + LangChain tool wrapper + audit logging
"""
from __future__ import annotations

import os
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any

from groq import AsyncGroq
from dotenv import load_dotenv
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from tools.helper.vector_store import ComplianceVectorStore
load_dotenv()

# Compliance agent core logic
class VectorComplianceAgent:
    """
    Vector-based compliance agent using semantic search + LLM interpretation
    
    Workflow:
    1. Build semantic search query from shipment context
    2. Search vector store for relevant regulations
    3. Use LLM to interpret regulations and make compliance decision
    4. Return structured compliance output
    """
    
    def __init__(self):
        # Initialize vector store with error handling
        try:
            self.vector_store = ComplianceVectorStore()
            doc_count = self.vector_store.count_documents()
            self.vector_enabled = True
            print("[COMPLIANCE AGENT] Vector store initialized")
            print(f"[COMPLIANCE AGENT] Database contains {doc_count} documents")
        except Exception as e:
            print(f"[COMPLIANCE AGENT] Vector store unavailable: {e}")
            print("[COMPLIANCE AGENT] Running in fallback mode")
            self.vector_store = None
            self.vector_enabled = False
        
        # Initialize LLM
        api_key = os.getenv('GROQ_API_KEY')
        if not api_key:
            raise ValueError("GROQ_API_KEY not found in environment")
        
        self.llm = AsyncGroq(api_key=api_key)
        self.model = "llama-3.3-70b-versatile"
        self.version = "1.0.0-unified"
    
    async def validate_compliance(
        self,
        shipment_id: str,
        container_id: str,
        window_id: str,
        event_type: str,
        risk_tier: str,
        details: Dict[str, Any],
        regulatory_tags: List[str] = None
    ) -> Dict:
        """
        Main compliance validation method
        
        Args:
            shipment_id: Shipment identifier
            container_id: Container identifier
            window_id: Time window identifier
            event_type: Event type (risk_assessment, excursion, etc.)
            risk_tier: Risk tier (LOW, MEDIUM, HIGH, CRITICAL)
            details: Shipment context including temp, duration, product, etc.
            regulatory_tags: Applicable regulatory frameworks
        
        Returns:
            Comprehensive compliance validation result
        """
        start_time = datetime.utcnow()
        
        # Extract and normalize data from details
        state = self._build_state(
            shipment_id, container_id, window_id, 
            event_type, risk_tier, details, regulatory_tags
        )
        
        # Build semantic search query
        query = self._build_search_query(state)
        print(f"[COMPLIANCE AGENT] Search query: {query[:100]}...")
        
        # Search for relevant regulations
        if self.vector_enabled:
            relevant_regs = self.vector_store.search(
                query=query,
                limit=5,
                similarity_threshold=0.3
            )
            print(f"[COMPLIANCE AGENT] Found {len(relevant_regs)} regulations")
        else:
            relevant_regs = self._get_fallback_regulations(state)
            print(f"[COMPLIANCE AGENT] Using {len(relevant_regs)} fallback regulations")
        
        # LLM interprets regulations and makes decision
        decision = await self._llm_interpret(state, relevant_regs)
        
        # Build output
        output = self._build_output(state, relevant_regs, decision)
        
        # Add timing
        duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        output['validation_duration_ms'] = duration_ms
        
        print(f"[COMPLIANCE AGENT] Decision: {output['compliance_status']}")
        print(f"[COMPLIANCE AGENT] Completed in {duration_ms}ms")
        
        return output
    
    def _build_state(
        self,
        shipment_id: str,
        container_id: str,
        window_id: str,
        event_type: str,
        risk_tier: str,
        details: Dict[str, Any],
        regulatory_tags: List[str]
    ) -> Dict:
        """Extract and normalize data into internal state"""
        
        # Extract with defaults
        product_category = details.get('product_category', 'standard_refrigerated')
        current_temp_c = float(details.get('current_temp_c', 
            details.get('temperature', details.get('temp', 0.0))))
        minutes_outside_range = int(details.get('minutes_outside_range',
            details.get('duration_minutes', details.get('excursion_duration', 0))))
        transit_phase = details.get('transit_phase', 
            details.get('phase', 'unknown'))
        spoilage_probability = float(details.get('spoilage_probability',
            details.get('ml_prob', 0.0)))
        at_risk_value = float(details.get('at_risk_value',
            details.get('estimated_loss', 0.0)))
        critical_patients_affected = int(details.get('critical_patients_affected', 0))
        affected_facilities = details.get('affected_facilities', [])
        
        # Convert risk_tier to numeric score
        risk_score = self._risk_tier_to_score(risk_tier)
        
        return {
            'shipment_id': shipment_id,
            'container_id': container_id,
            'window_id': window_id,
            'event_type': event_type,
            'product_category': product_category,
            'current_temp_c': current_temp_c,
            'minutes_outside_range': minutes_outside_range,
            'transit_phase': transit_phase,
            'risk_score': risk_score,
            'risk_tier': risk_tier,
            'spoilage_probability': spoilage_probability,
            'at_risk_value': at_risk_value,
            'critical_patients_affected': critical_patients_affected,
            'affected_facilities': affected_facilities,
            'regulatory_tags': regulatory_tags or []
        }
    
    def _risk_tier_to_score(self, risk_tier: str) -> int:
        """Convert risk tier to numeric score"""
        mapping = {'LOW': 25, 'MEDIUM': 50, 'HIGH': 75, 'CRITICAL': 95}
        return mapping.get(risk_tier.upper(), 50)
    
    def _build_search_query(self, state: Dict) -> str:
        """Build semantic search query"""
        return f"""
{state['product_category']} pharmaceutical product 
temperature excursion {state['minutes_outside_range']} minutes
risk score {state['risk_score']}
regulatory requirements approval deviation report
""".strip()
    
    def _get_fallback_regulations(self, state: Dict) -> List[Dict]:
        """Fallback regulations when vector store unavailable"""
        fallback = [
            {
                'regulation_id': 'FDA-CFR-211.142',
                'regulation_name': 'Temperature Control Requirements',
                'authority': 'FDA',
                'section': '21 CFR 211.142',
                'similarity': 0.85,
                'content': 'Pharmaceutical products must be stored and transported within specified temperature ranges.',
                'metadata': {'url': 'https://www.fda.gov'}
            },
            {
                'regulation_id': 'ICH-Q1A',
                'regulation_name': 'Stability Testing Guidelines',
                'authority': 'ICH',
                'section': 'Q1A(R2)',
                'similarity': 0.78,
                'content': 'Stability testing provides evidence on how pharmaceutical quality varies with environmental factors.',
                'metadata': {'url': 'https://www.ich.org'}
            }
        ]
        
        if state['product_category'] == 'biologics':
            fallback.append({
                'regulation_id': 'FDA-CFR-600.15',
                'regulation_name': 'Biologics Temperature Requirements',
                'authority': 'FDA',
                'section': '21 CFR 600.15',
                'similarity': 0.92,
                'content': 'Biological products require strict temperature control.',
                'metadata': {'url': 'https://www.fda.gov'}
            })
        
        return fallback
    
    async def _llm_interpret(self, state: Dict, relevant_regs: List[Dict]) -> Dict:
        """LLM interprets regulations and makes compliance decision"""
        
        regulatory_context = "\n".join([
            f"REGULATION {i+1}: {r['regulation_id']} - {r['regulation_name']}\n{r['content'][:400]}"
            for i, r in enumerate(relevant_regs)
        ])
        
        prompt = f"""You are a pharmaceutical regulatory compliance expert.

SHIPMENT CONTEXT:
- ID: {state['shipment_id']} | Container: {state['container_id']}
- Product: {state['product_category']}
- Temperature: {state['current_temp_c']}°C for {state['minutes_outside_range']} min
- Transit Phase: {state['transit_phase']}
- Risk: {state['risk_tier']} ({state['risk_score']}/100)
- Spoilage Prob: {state['spoilage_probability']*100:.1f}%
- Patients: {state['critical_patients_affected']} critical
- Value: ${state['at_risk_value']:,.0f}

REGULATIONS:
{regulatory_context}

Provide compliance assessment as JSON:
{{
  "compliance_decision": "compliant|violation|borderline",
  "severity": "minor|major|critical",
  "human_approval_required": true|false,
  "approval_level": "operator|qa_manager|director|none",
  "product_disposition": "release|quarantine|destroy|investigate",
  "deviation_report_required": true|false,
  "reasoning": "brief explanation with citations",
  "violated_regulations": ["REG-ID"],
  "required_actions": ["action"]
}}
"""
        
        try:
            response = await self.llm.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a pharmaceutical regulatory expert. Respond only with valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0,
                max_tokens=1500,
                response_format={"type": "json_object"}
            )
            
            return json.loads(response.choices[0].message.content)
            
        except Exception as e:
            print(f"[ERROR] LLM interpretation failed: {e}")
            # Conservative fallback
            return {
                "compliance_decision": "violation",
                "severity": "major",
                "human_approval_required": True,
                "approval_level": "qa_manager",
                "product_disposition": "quarantine",
                "deviation_report_required": True,
                "reasoning": "LLM failed, conservative default",
                "violated_regulations": [],
                "required_actions": ["Manual review required"]
            }
    
    def _build_output(self, state: Dict, relevant_regs: List[Dict], decision: Dict) -> Dict:
        """Build final compliance output"""
        
        violations = []
        if decision.get('compliance_decision') == 'violation':
            violations = [{
                'violation_type': reg_id,
                'severity': decision.get('severity', 'MAJOR').upper(),
                'regulation': reg_id,
                'description': f"Violation of {reg_id}",
                'action_required': ', '.join(decision.get('required_actions', []))
            } for reg_id in decision.get('violated_regulations', [])]
        
        regulations_checked = list(set(
            f"{r['authority']} - {r['regulation_name']}" for r in relevant_regs
        ))
        
        return {
            # Original fields
            'shipment_id': state['shipment_id'],
            'container_id': state['container_id'],
            'window_id': state['window_id'],
            'event_type': state['event_type'],
            'risk_tier': state['risk_tier'],
            'regulatory_tags': state['regulatory_tags'],
            
            # Compliance decision
            'compliance_status': decision.get('compliance_decision', 'violation'),
            'compliance_score': 100 if decision.get('compliance_decision') == 'compliant' else 50,
            'regulations_checked': regulations_checked,
            'violations': violations,
            'warnings': [],
            
            # Approval
            'human_approval_required': decision.get('human_approval_required', True),
            'approval_reason': decision.get('reasoning'),
            'approval_level': decision.get('approval_level', 'qa_manager'),
            'approval_urgency': 'immediate' if decision.get('approval_level') == 'director' else 'within_24h',
            
            # Disposition
            'product_disposition': decision.get('product_disposition', 'quarantine'),
            'disposition_justification': decision.get('reasoning'),
            'deviation_report_required': decision.get('deviation_report_required', False),
            
            # Audit
            'audit_trail_generated': True,
            'audit_record_id': f"AUDIT-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            
            # Citations
            'applicable_citations': [{
                'regulation': r['regulation_id'],
                'title': r['regulation_name'],
                'url': r['metadata'].get('url'),
                'similarity': r.get('similarity')
            } for r in relevant_regs],
            
            # Metadata
            'decision_method': 'vector_search_llm',
            'validated_at': datetime.utcnow().isoformat(),
            'agent_version': self.version
        }


# Langchain tool wrapper

# Directory for audit logs
LOG_DIR = Path(__file__).resolve().parent.parent / "audit_logs"

# Global agent instance (reused across calls)
_compliance_agent = None

def get_compliance_agent() -> VectorComplianceAgent:
    """Get or create global compliance agent instance"""
    global _compliance_agent
    if _compliance_agent is None:
        _compliance_agent = VectorComplianceAgent()
    return _compliance_agent


class ComplianceInput(BaseModel):
    """Input schema for compliance tool"""
    shipment_id: str
    container_id: str
    window_id: str
    event_type: str = Field(
        description="Event type: risk_assessment, excursion, action_taken, approval_decision"
    )
    risk_tier: str = Field(
        description="Risk tier: LOW, MEDIUM, HIGH, CRITICAL"
    )
    details: Dict[str, Any] = Field(
        description="Shipment context (product_category, current_temp_c, minutes_outside_range, etc.)"
    )
    regulatory_tags: List[str] | None = Field(
        default_factory=list,
        description="Regulatory frameworks: GDP, FDA_21CFR11, WHO_PQS, DSCSA"
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
    Execute compliance validation with audit logging
    
    This function:
    1. Logs audit event (immutable record)
    2. Validates compliance using VectorComplianceAgent
    3. Returns combined results
    """
    
    # 1. AUDIT LOGGING
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

    # 2. COMPLIANCE VALIDATION
    compliance_result = None
    compliance_error = None
    
    try:
        agent = get_compliance_agent()
        
        # Run async validation in sync context
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        compliance_result = loop.run_until_complete(
            agent.validate_compliance(
                shipment_id=shipment_id,
                container_id=container_id,
                window_id=window_id,
                event_type=event_type,
                risk_tier=risk_tier,
                details=details,
                regulatory_tags=regulatory_tags or []
            )
        )
        
    except Exception as e:
        compliance_error = str(e)
        print(f"[COMPLIANCE TOOL] Validation failed: {e}")

    # 3. COMBINED RESULTS
    result = {
        "tool": "compliance_agent",
        "status": "completed" if compliance_result else "audit_only",
        "log_id": log_id,
        "log_path": str(log_path),
        "timestamp": timestamp,
    }
    
    if compliance_result:
        result.update({
            "compliance_validation": compliance_result,
            "compliance_status": compliance_result.get("compliance_status"),
            "human_approval_required": compliance_result.get("human_approval_required"),
            "product_disposition": compliance_result.get("product_disposition"),
            "violations": compliance_result.get("violations", []),
            "regulations_checked": compliance_result.get("regulations_checked", []),
        })
    else:
        result.update({
            "compliance_validation": None,
            "compliance_error": compliance_error,
            "compliance_status": "validation_failed",
            "human_approval_required": True,  # Conservative
            "product_disposition": "quarantine",  # Conservative
        })

    return result


# Create LangChain tool
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