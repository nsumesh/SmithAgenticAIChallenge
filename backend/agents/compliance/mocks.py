# Mock Compliance Agent - for testing without LLM
import asyncio

class MockComplianceAgent:

    async def validate_compliance(self, state: dict) -> dict:
        # simulate compliance validation
        print(f"[MOCK] Compliance Agent validating actions for shipment {state['shipment_id']}")
        
        await asyncio.sleep(0.3)
        
        risk_score = state['risk_assessment']['score']
        
        return {
            'compliance_status': 'compliant' if risk_score < 70 else 'violation_detected',
            'compliance_score': max(0, 100 - risk_score),
            'regulations_checked': [
                'GDP 5.2.3 - Temperature Excursion Handling',
                'FDA 21CFR11 - Electronic Records',
                'EU GDP Annex 1 - Quality Management'
            ],
            'violations': [
                {
                    'violation_type': 'TEMPERATURE_EXCURSION',
                    'severity': 'MAJOR' if risk_score > 70 else 'MINOR',
                    'regulation': 'GDP 5.2.3',
                    'description': f'Risk score {risk_score} exceeds threshold'
                }
            ] if risk_score > 70 else [],
            'warnings': [
                'Temperature excursion >30min requires deviation report within 24hr'
            ] if state['minutes_outside_range'] > 30 else [],
            'human_approval_required': risk_score > 70,
            'approval_reason': f'Risk score {risk_score} exceeds threshold' if risk_score > 70 else None,
            'approval_level': 'qa_manager' if 70 < risk_score < 85 else 'director' if risk_score >= 85 else None,
            'audit_trail_generated': True,
            'decision_method': 'mock'
        }