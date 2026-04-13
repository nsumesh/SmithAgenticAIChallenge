# LLM interpreter for compliance edge cases - using Groq for complex scenarios
import os
import json
from groq import AsyncGroq
from typing import Dict, List, Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class ComplianceLLMInterpreter:
    # uses Groq LLM for edge case interpretation
    def __init__(self):
        api_key = os.getenv('GROQ_API_KEY')
        if not api_key:
            raise ValueError("GROQ_API_KEY not found in environment")
        
        self.client = AsyncGroq(api_key=api_key)
        self.model = "llama-3.3-70b-versatile"  # Current Groq model (2026)
    
    async def interpret_edge_case(
        self,
        shipment_data: Dict,
        triggered_rules: List[Dict],
        rule_conflicts: Optional[List[str]] = None
    ):
        # use LLM to interpret complex/borderline compliance scenarios
        
        prompt = self._build_prompt(shipment_data, triggered_rules, rule_conflicts)
        
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": self._get_system_prompt()
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.0,  # Deterministic for compliance
                max_tokens=1500,
                response_format={"type": "json_object"}  # Force JSON output
            )
            
            llm_decision = json.loads(response.choices[0].message.content)
            
            return {
                'llm_used': True,
                'llm_model': self.model,
                'compliance_decision': llm_decision.get('compliance_decision'),
                'reasoning': llm_decision.get('reasoning'),
                'recommended_approval_level': llm_decision.get('approval_level'),
                'product_disposition': llm_decision.get('product_disposition'),
                'additional_actions': llm_decision.get('additional_actions', [])
            }
            
        except Exception as e:
            print(f"Error - LLM interpreter failed: {e}")
            # fallback conservative decision
            return {
                'llm_used': False,
                'error': str(e),
                'fallback_decision': 'CONSERVATIVE',
                'reasoning': 'LLM failed, defaulting to strictest rule interpretation'
            }
    
    def _get_system_prompt(self) -> str:
        # system prompt for compliance LLM
        return """You are a pharmaceutical regulatory compliance expert specializing in cold chain logistics.

Your role:
- Interpret EU GDP, FDA 21 CFR Part 11, WHO TRS 961, and ICH guidelines
- Make conservative decisions when data is ambiguous
- Consider product safety as paramount
- Cite specific regulatory sections
- Balance patient safety vs operational cost

Key principles:
1. Patient safety > cost savings
2. Biologics require stricter controls than standard refrigerated drugs
3. When in doubt, escalate to higher approval level
4. Always consider product stability data

Output format: Valid JSON only with these exact fields:
{
  "compliance_decision": "compliant|violation|borderline",
  "reasoning": "2-3 sentence explanation with regulatory citations",
  "approval_level": "operator|qa_manager|director|none",
  "product_disposition": "release|quarantine|destroy|investigate",
  "additional_actions": ["action1", "action2"]
}"""
    
    def _build_prompt(
        self,
        shipment_data: Dict,
        triggered_rules: List[Dict],
        rule_conflicts: Optional[List[str]]
    ):
        # build user prompt with scenario details
        
        prompt = f"""COMPLIANCE EDGE CASE REVIEW

SHIPMENT DETAILS:
- Shipment ID: {shipment_data.get('shipment_id')}
- Product Category: {shipment_data.get('product_category')}
- Current Temperature: {shipment_data.get('current_temp_c')}°C
- Minutes Outside Range: {shipment_data.get('minutes_outside_range')}
- Transit Phase: {shipment_data.get('transit_phase')}

RISK ASSESSMENT (ML Model):
- Risk Score: {shipment_data.get('risk_score')}/100
- Spoilage Probability: {shipment_data.get('spoilage_probability', 0) * 100:.1f}%

RULES TRIGGERED:
{json.dumps(triggered_rules, indent=2)}

FINANCIAL IMPACT:
- At-Risk Value: ${shipment_data.get('at_risk_value', 0):,.2f}
- Proposed Intervention Cost: ${shipment_data.get('proposed_intervention_cost', 0):,.2f}

AFFECTED STAKEHOLDERS:
- Critical Patients: {shipment_data.get('critical_patients_affected', 0)}
- Total Facilities: {len(shipment_data.get('affected_facilities', []))}
"""
        
        if rule_conflicts:
            prompt += f"\nRULE CONFLICTS DETECTED:\n{json.dumps(rule_conflicts, indent=2)}\n"
        
        prompt += """
QUESTION:
This is a borderline/complex case. Please provide:
1. Compliance decision (compliant/violation/borderline)
2. Recommended approval level
3. Product disposition (release/quarantine/destroy)
4. Justification with regulatory citations

Respond ONLY with valid JSON matching the schema.
"""
        
        return prompt