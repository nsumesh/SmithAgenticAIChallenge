import asyncio
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.compliance.agent import VectorComplianceAgent

async def test():
    agent = VectorComplianceAgent()
    
    # ORIGINAL FORMAT (what upstream sends)
    result = await agent.validate_compliance(
        shipment_id='S001',
        container_id='C001',
        window_id='W001',
        event_type='risk_assessment',
        risk_tier='HIGH',
        details={
            'product_category': 'biologics',
            'current_temp_c': 9.5,
            'minutes_outside_range': 45,
            'transit_phase': 'customs_clearance',
            'spoilage_probability': 0.42,
            'at_risk_value': 145000,
            'critical_patients_affected': 12,
            'affected_facilities': ['HOSP-001']
        },
        regulatory_tags=['GDP', 'FDA_21CFR11', 'WHO_PQS']
    )
    
    print("\n" + "="*80)
    print("COMPLIANCE VALIDATION RESULT")
    print("="*80)
    
    # Original fields
    print(f"\nShipment ID: {result['shipment_id']}")
    print(f"Container ID: {result['container_id']}")
    print(f"Window ID: {result['window_id']}")
    print(f"Event Type: {result['event_type']}")
    print(f"Risk Tier: {result['risk_tier']}")
    print(f"Regulatory Tags: {', '.join(result['regulatory_tags'])}")
    
    # Compliance decision
    print(f"\nCompliance Status: {result['compliance_status']}")
    print(f"Compliance Score: {result['compliance_score']}")
    print(f"Approval Required: {result['human_approval_required']}")
    print(f"Approval Level: {result['approval_level']}")
    print(f"Approval Urgency: {result['approval_urgency']}")
    print(f"Product Disposition: {result['product_disposition']}")
    
    # Violations
    if result['violations']:
        print(f"\nViolations Detected: {len(result['violations'])}")
        for v in result['violations']:
            print(f"  - {v['regulation']}: {v['description']}")
    
    # Regulations found
    print(f"\nRegulations Checked ({len(result['regulations_checked'])}):")
    for reg in result['regulations_checked']:
        print(f"  - {reg}")
    
    print(f"\nTop Relevant Citations:")
    for citation in result['applicable_citations'][:3]:
        print(f"  - {citation['regulation']} (similarity: {citation.get('similarity', 0):.3f})")
        print(f"    {citation['title']}")
    
    print(f"\nReasoning:")
    print(f"  {result['approval_reason']}")
    
    # Audit
    print(f"\nAudit Record: {result['audit_record_id']}")
    print(f"Validated At: {result['validated_at']}")
    print(f"Duration: {result['validation_duration_ms']}ms")
    print(f"Method: {result['decision_method']}")
    
    print("="*80)

asyncio.run(test())