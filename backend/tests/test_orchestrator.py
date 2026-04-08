# script to test orchestrator workflow
import asyncio
from datetime import datetime
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.agents.orchestrator import OrchestratorAgent
from src.models.state import AnomalyType, TransitPhase

# low risk scenario - no human approval needed
async def test_low_risk_workflow():
    print("Test 1: Low Risk Workflow (Risk Score: 45)")
    
    orchestrator = OrchestratorAgent()
    
    test_state = {
        'shipment_id': 'S001',
        'container_id': 'C330',
        'product_id': 'P02',
        'anomaly_type': AnomalyType.TEMPERATURE_EXCURSION,
        'detected_at': datetime.utcnow().isoformat(),
        'current_temp_c': 6.5,
        'temp_slope_c_per_hr': 0.3,
        'current_delay_min': 15.0,
        'transit_phase': TransitPhase.LOADING_ZONE,
        'minutes_outside_range': 10,
        'risk_assessment': {
            'score': 45,
            'spoilage_probability': 0.12,
            'confidence': 'medium',
            'reasoning': 'Minor temperature excursion, trending stable',
            'trigger_orchestrator': True,
            'recommended_urgency': 'medium',
            'breakdown': {
                'rule_based_score': 40,
                'bayesian_probability': 0.15,
                'trend_severity': 'stable'
            }
        }
    }
    
    result = await orchestrator.invoke(test_state)
    
    print("\nValidating results for low-risk workflow:")

    assert result['shipment_id'] == 'S001', "Shipment ID mismatch"
    assert result['prioritized_facilities'] is not None, "No facilities prioritized"
    assert result['inventory_actions'] is not None, "No inventory actions"
    assert result['compliance_check'] is not None, "No compliance check"
    assert result['human_approval_required'] == False, "Should not require approval"
    assert len(result['notifications_sent']) > 0, "No notifications sent"
    
    print(f"Workflow completed successfully: {len(result['prioritized_facilities'])} facilities, "
          f"{len(result['notifications_sent'])} notifications sent")
    
    print("Test 1 completed successfully!")

    return result

# high risk scenario - human approval needed
async def test_high_risk_workflow():
    print("Test 2: High Risk Workflow (Risk Score: 82)")
    
    orchestrator = OrchestratorAgent()
    
    test_state = {
        'shipment_id': 'S042',
        'container_id': 'C410',
        'product_id': 'P01',
        'anomaly_type': AnomalyType.COMPOUND_RISK,
        'detected_at': datetime.utcnow().isoformat(),
        'current_temp_c': 9.2,
        'temp_slope_c_per_hr': 1.4,
        'current_delay_min': 245.0,
        'transit_phase': TransitPhase.CUSTOMS_CLEARANCE,
        'minutes_outside_range': 35,
        'risk_assessment': {
            'score': 82,
            'spoilage_probability': 0.42,
            'confidence': 'high',
            'reasoning': 'Critical temperature excursion with rapid warming trend',
            'trigger_orchestrator': True,
            'recommended_urgency': 'immediate',
            'breakdown': {
                'rule_based_score': 75,
                'bayesian_probability': 0.45,
                'trend_severity': 'increasing'
            }
        }
    }
    
    result = await orchestrator.invoke(test_state)

    print("\nValidating results for high-risk workflow:")
    
    assert result['shipment_id'] == 'S042', "Shipment ID mismatch"
    assert result['risk_assessment']['score'] == 82, "Risk score mismatch"
    assert result['human_approval_required'] == True, "Should require approval"
    assert result['human_approved'] == True, "Should be approved (mock auto-approves)"
    assert result['inventory_actions']['reorder_triggered'] == True, "Should trigger reorder"
    assert len(result['actions_taken']) > 0, "No actions executed"
    
    print(f"High-risk workflow completed: Risk score {result['risk_assessment']['score']}, "
          f"approval granted, {len(result['actions_taken'])} actions executed")
    
    print("\nTest 2 completed successfully!\n")
    return result


async def test_workflow_outputs():
    print("Test 3: Validate All Agent Outputs")
    
    orchestrator = OrchestratorAgent()
    
    test_state = {
        'shipment_id': 'S003',
        'container_id': 'C330',
        'product_id': 'P02',
        'anomaly_type': AnomalyType.DELAY_CASCADE,
        'detected_at': datetime.utcnow().isoformat(),
        'current_temp_c': 5.0,
        'temp_slope_c_per_hr': 0.2,
        'current_delay_min': 60.0,
        'transit_phase': TransitPhase.AIR_HANDOFF,
        'minutes_outside_range': 0,
        'risk_assessment': {
            'score': 50,
            'spoilage_probability': 0.2,
            'confidence': 'medium',
            'reasoning': 'Moderate delay detected',
            'trigger_orchestrator': True,
            'recommended_urgency': 'medium',
            'breakdown': {}
        }
    }
    
    result = await orchestrator.invoke(test_state)
    
    print("Validating agent outputs:")

    checks = [
        ('prioritized_facilities', "Hospital Priority Agent"),
        ('inventory_actions', "Inventory Agent"),
        ('compliance_check', "Compliance Agent"),
        ('actions_taken', "Action Agent"),
        ('notifications_sent', "Notification Agent")
    ]
    
    for field, agent_name in checks:
        assert field in result and result[field] is not None, f"{agent_name} didn't run"
        print(f"{agent_name} output present")
    
    # Check metadata
    assert 'workflow_id' in result, "No workflow ID"
    print("Workflow ID generated")
    
    assert 'created_at' in result, "No created_at timestamp"
    print("Timestamps present")
    
    print("\nTest 3 completed successfully!\n")
    return result

async def main():
    print("Running orchestrator tests")
    try:
        result1 = await test_low_risk_workflow()
        result2 = await test_high_risk_workflow()
        result3 = await test_workflow_outputs()

        print("\nOverall summary \nWorkflow IDs:")
        print(f"Test 1: {result1['workflow_id']}")
        print(f"Test 2: {result2['workflow_id']}")
        print(f"Test 3: {result3['workflow_id']}")
        print("\nOrchestrator is working correctly!\n")
        
    except AssertionError as e:
        print(f"\nTest Failed: {e}\n")
        raise
    except Exception as e:
        print(f"\\Error: {e}\n")
        raise


if __name__ == "__main__":
    asyncio.run(main())