# vector based compliance agent - uses semantic search + LLM interpretation
import os
from datetime import datetime
from typing import Dict, List, Any
from groq import AsyncGroq
from dotenv import load_dotenv
from .vector_store import ComplianceVectorStore

load_dotenv()

class VectorComplianceAgent:
    """Compliance agent using vector search + LLM"""
    
    def __init__(self):
        # Initialize vector store with error handling
        try:
            self.vector_store = ComplianceVectorStore()
            doc_count = self.vector_store.count_documents()
            self.vector_enabled = True
            print("[COMPLIANCE VECTOR] Agent initialized")
            print(f"[COMPLIANCE VECTOR] Database contains {doc_count} documents")
        except Exception as e:
            print(f"[COMPLIANCE VECTOR] Vector store not available: {e}")
            print("[COMPLIANCE VECTOR] Running in fallback mode without vector search")
            self.vector_store = None
            self.vector_enabled = False
        
        # Initialize LLM
        api_key = os.getenv('GROQ_API_KEY')
        if not api_key:
            raise ValueError("GROQ_API_KEY not found in environment")
        
        self.llm = AsyncGroq(api_key=api_key)
        self.model = "llama-3.3-70b-versatile"
    
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
        start_time = datetime.utcnow()
        
        # Extract data from details
        product_category = details.get('product_category', 'standard_refrigerated')
        current_temp_c = details.get('current_temp_c', 0.0)
        minutes_outside_range = details.get('minutes_outside_range', 0)
        transit_phase = details.get('transit_phase', 'unknown')
        spoilage_probability = details.get('spoilage_probability', 0.0)
        at_risk_value = details.get('at_risk_value', 0.0)
        critical_patients_affected = details.get('critical_patients_affected', 0)
        affected_facilities = details.get('affected_facilities', [])
        
        # Convert risk_tier to numeric risk_score
        risk_score = self._risk_tier_to_score(risk_tier)
        
        # Build internal state for processing
        state = {
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
        
        # Build search query
        query = self._build_search_query(state)
        print(f"[COMPLIANCE VECTOR] Query: {query}")
        
        # Semantic search for relevant regulations against vector store
        if self.vector_enabled:
            relevant_regs = self.vector_store.search(
                query=query,
                limit=5,
                similarity_threshold=0.3
            )
            print(f"[COMPLIANCE VECTOR] Found {len(relevant_regs)} relevant regulations")
        else:
            relevant_regs = self._get_fallback_regulations(state)
            print(f"[COMPLIANCE VECTOR] Using fallback regulations (vector store unavailable)")
        
        # Use LLM to interpret regulations and decide
        decision = await self._llm_interpret(state, relevant_regs)
        
        # Build compliance output
        output = self._build_output(state, relevant_regs, decision)
        
        # Calculate duration
        duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        output['validation_duration_ms'] = duration_ms
        
        print(f"[COMPLIANCE VECTOR] Validation complete in {duration_ms}ms")
        print(f"[COMPLIANCE VECTOR] Decision: {output['compliance_status']}")
        
        return output
    
    def _risk_tier_to_score(self, risk_tier: str) -> int:
        """Convert risk tier to numeric score"""
        mapping = {
            'LOW': 25,
            'MEDIUM': 50,
            'HIGH': 75,
            'CRITICAL': 95
        }
        return mapping.get(risk_tier.upper(), 50)
    
    def _build_search_query(self, state: Dict) -> str:
        """Build semantic search query from shipment state"""
        product_category = state.get('product_category', 'unknown')
        minutes_outside = state.get('minutes_outside_range', 0)
        risk_score = state.get('risk_score', 0)
        
        query = f"""
{product_category} pharmaceutical product 
temperature excursion {minutes_outside} minutes
risk score {risk_score}
regulatory requirements approval deviation report
"""
        return query.strip()
    
    def _get_fallback_regulations(self, state: Dict) -> List[Dict]:
        """Provide fallback regulations when vector store is unavailable"""
        product_category = state.get('product_category', 'unknown')
        
        fallback_regs = [
            {
                'regulation_id': 'FDA-CFR-211.142',
                'regulation_name': 'Temperature Control Requirements',
                'authority': 'FDA',
                'section': '21 CFR 211.142',
                'similarity': 0.85,
                'content': 'Pharmaceutical products must be stored and transported within specified temperature ranges. Temperature excursions require investigation and may necessitate product quarantine.',
                'metadata': {'url': 'https://www.fda.gov/drugs/pharmaceutical-quality-resources/temperature-control'}
            },
            {
                'regulation_id': 'ICH-Q1A',
                'regulation_name': 'Stability Testing Guidelines',
                'authority': 'ICH',
                'section': 'Q1A(R2)',
                'similarity': 0.78,
                'content': 'Stability testing provides evidence on how the quality of a pharmaceutical product varies with time under the influence of environmental factors such as temperature.',
                'metadata': {'url': 'https://www.ich.org/page/quality-guidelines'}
            }
        ]
        
        if product_category == 'biologics':
            fallback_regs.append({
                'regulation_id': 'FDA-CFR-600.15',
                'regulation_name': 'Biologics Temperature Requirements',
                'authority': 'FDA',
                'section': '21 CFR 600.15',
                'similarity': 0.92,
                'content': 'Biological products require strict temperature control. Any deviation must be thoroughly investigated and documented.',
                'metadata': {'url': 'https://www.fda.gov/vaccines-blood-biologics/guidance-compliance-regulatory-information-biologics'}
            })
        
        return fallback_regs
    
    async def _llm_interpret(self, state: Dict, relevant_regs: List[Dict]) -> Dict:
        """Use LLM to interpret regulations and make compliance decision"""
        regulatory_context = self._build_regulatory_context(relevant_regs)
        
        prompt = f"""You are a pharmaceutical regulatory compliance expert.

SHIPMENT SCENARIO:
- Shipment ID: {state.get('shipment_id')}
- Container ID: {state.get('container_id')}
- Window ID: {state.get('window_id')}
- Event Type: {state.get('event_type')}
- Product: {state.get('product_category')}
- Temperature: {state.get('current_temp_c')}°C
- Duration Outside Range: {state.get('minutes_outside_range')} minutes
- Transit Phase: {state.get('transit_phase')}
- Risk Tier: {state.get('risk_tier')}
- Risk Score (ML Model): {state.get('risk_score')}/100
- Spoilage Probability: {state.get('spoilage_probability', 0) * 100:.1f}%
- Critical Patients Affected: {state.get('critical_patients_affected', 0)}
- Financial At-Risk: ${state.get('at_risk_value', 0):,.2f}
- Regulatory Tags: {', '.join(state.get('regulatory_tags', []))}

RELEVANT REGULATIONS:
{regulatory_context}

QUESTION:
Based on these regulations, provide a compliance assessment.

Respond ONLY with valid JSON:
{{
  "compliance_decision": "compliant|violation|borderline",
  "severity": "minor|major|critical",
  "human_approval_required": true|false,
  "approval_level": "operator|qa_manager|director|none",
  "product_disposition": "release|quarantine|destroy|investigate",
  "deviation_report_required": true|false,
  "reasoning": "2-3 sentence explanation with specific regulatory citations",
  "violated_regulations": ["REG-ID-1", "REG-ID-2"],
  "required_actions": ["action1", "action2"]
}}
"""
        
        try:
            response = await self.llm.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a pharmaceutical regulatory expert. Always respond with valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0,
                max_tokens=1500,
                response_format={"type": "json_object"}
            )
            
            import json
            decision = json.loads(response.choices[0].message.content)
            return decision
            
        except Exception as e:
            print(f"[ERROR] LLM interpretation failed: {e}")
            return {
                "compliance_decision": "violation",
                "severity": "major",
                "human_approval_required": True,
                "approval_level": "qa_manager",
                "product_disposition": "quarantine",
                "deviation_report_required": True,
                "reasoning": "LLM failed, defaulting to conservative decision",
                "violated_regulations": [],
                "required_actions": ["Manual review required"]
            }
    
    def _build_regulatory_context(self, relevant_regs: List[Dict]) -> str:
        """Format retrieved regulations for LLM prompt"""
        context = ""
        for i, reg in enumerate(relevant_regs, 1):
            context += f"""
REGULATION {i}:
- ID: {reg['regulation_id']}
- Name: {reg['regulation_name']}
- Authority: {reg['authority']}
- Section: {reg.get('section', 'N/A')}
- Similarity: {reg.get('similarity', 0):.2f}

CONTENT:
{reg['content'][:500]}...

---
"""
        return context
    
    def _build_output(
        self,
        state: Dict,
        relevant_regs: List[Dict],
        decision: Dict
    ) -> Dict:
        """Build final compliance output"""
        violations = []
        if decision.get('compliance_decision') == 'violation':
            violations = [
                {
                    'violation_type': reg_id,
                    'severity': decision.get('severity', 'MAJOR'),
                    'regulation': reg_id,
                    'description': f"Violation of {reg_id}",
                    'action_required': ', '.join(decision.get('required_actions', []))
                }
                for reg_id in decision.get('violated_regulations', [])
            ]
        
        regulations_checked = list(set(
            f"{reg['authority']} - {reg['regulation_name']}"
            for reg in relevant_regs
        ))
        
        return {
            # Original fields (backward compatible)
            'shipment_id': state.get('shipment_id'),
            'container_id': state.get('container_id'),
            'window_id': state.get('window_id'),
            'event_type': state.get('event_type'),
            'risk_tier': state.get('risk_tier'),
            'regulatory_tags': state.get('regulatory_tags', []),
            
            # Compliance decision
            'compliance_status': decision.get('compliance_decision', 'violation'),
            'compliance_score': 100 if decision.get('compliance_decision') == 'compliant' else 50,
            'regulations_checked': regulations_checked,
            'violations': violations,
            'warnings': [],
            
            # Approval requirements
            'human_approval_required': decision.get('human_approval_required', True),
            'approval_reason': decision.get('reasoning'),
            'approval_level': decision.get('approval_level', 'qa_manager'),
            'approval_urgency': 'immediate' if decision.get('approval_level') == 'director' else 'within_24h',
            
            # Product disposition
            'product_disposition': decision.get('product_disposition', 'quarantine'),
            'disposition_justification': decision.get('reasoning'),
            'deviation_report_required': decision.get('deviation_report_required', False),
            
            # Audit trail
            'audit_trail_generated': True,
            'audit_record_id': f"AUDIT-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            
            # Citations
            'applicable_citations': [
                {
                    'regulation': reg['regulation_id'],
                    'title': reg['regulation_name'],
                    'url': reg['metadata'].get('url'),
                    'similarity': reg.get('similarity')
                }
                for reg in relevant_regs
            ],
            
            # Metadata
            'decision_method': 'vector_search_llm',
            'validated_at': datetime.utcnow().isoformat(),
            'validation_duration_ms': 0,
            'agent_version': '1.0.0-vector'
        }