# mock agents for testing orchestrator
import asyncio
from typing import Dict, Any
from src.models.state import OrchestratorState

# hospital priority agent mock - returns dummy facility data
class MockHospitalPriorityAgent:    
    async def score_facilities(self, state):
        print(f"Hospital Priority Agent processing shipment {state['shipment_id']}")
        
        # processing time
        await asyncio.sleep(0.5)
        
        # mock prioritized facilities
        state['prioritized_facilities'] = [
            {
                'facility_id': 'HOSP-001',
                'facility_name': 'Memorial Pediatric Cancer Center',
                'priority_score': 94.0,
                'urgency_breakdown': {
                    'appointment_urgency': 100.0,
                    'patient_vulnerability': 95.0,
                    'backup_availability': 0.0,
                    'patient_volume': 85.0
                },
                'contact_method': 'erp_webhook',
                'patients_affected': 120,
                'critical_patients': 87
            },
            {
                'facility_id': 'HOSP-008',
                'facility_name': 'Community Health Clinic',
                'priority_score': 62.0,
                'urgency_breakdown': {
                    'appointment_urgency': 60.0,
                    'patient_vulnerability': 45.0,
                    'backup_availability': 30.0,
                    'patient_volume': 50.0
                },
                'contact_method': 'voice_ivr',
                'patients_affected': 45,
                'critical_patients': 12
            }
        ]
        
        print(f"Prioritized {len(state['prioritized_facilities'])} facilities")
        return state


# inventory agent mock - returns dummy inventory data
class MockInventoryAgent:    
    async def manage_inventory(self, state):
        print(f"Inventory Agent processing shipment {state['shipment_id']}")
        
        await asyncio.sleep(0.5)
        
        state['inventory_actions'] = {
            'backup_available': True,
            'backup_location': 'WAREHOUSE-BOS-02',
            'reorder_triggered': state['risk_assessment']['score'] > 70,
            'reallocation_plan': {
                'source_warehouse': 'WAREHOUSE-BOS-02',
                'destinations': ['HOSP-001', 'HOSP-008'],
                'quantities': [300, 200],
                'delivery_method': 'emergency_courier',
                'eta_hours': 6
            } if state['risk_assessment']['score'] > 70 else None,
            'financial_impact': {
                'at_risk_value': 145000.0,
                'reorder_cost': 95000.0 if state['risk_assessment']['score'] > 70 else 0.0,
                'reallocation_cost': 2500.0 if state['risk_assessment']['score'] > 70 else 0.0,
                'net_loss_if_spoiled': 92500.0
            }
        }
        
        print(f"Inventory action: Reorder triggered = {state['inventory_actions']['reorder_triggered']}")
        return state


# appointment agent mock - returns dummy appointment data
# class MockAppointmentAgent:    
#     async def coordinate_appointments(self, state):
#         print(f"Appointment Agent processing {len(state.get('prioritized_facilities', []))} facilities")
        
#         await asyncio.sleep(0.5)
        
#         state['appointment_coordination'] = {
#             'total_appointments_affected': 165,
#             'patients_rescheduled': 45,
#             'patients_proceeding_as_scheduled': 120,
#             'facility_actions': [
#                 {
#                     'facility_id': 'HOSP-001',
#                     'action': 'use_backup_supply',
#                     'critical_patients_affected': 0,
#                     'routine_patients_rescheduled': 0
#                 },
#                 {
#                     'facility_id': 'HOSP-008',
#                     'action': 'reschedule',
#                     'critical_patients_affected': 12,
#                     'routine_patients_rescheduled': 33
#                 }
#             ]
#         }
        
#         print(f"{state['appointment_coordination']['patients_rescheduled']} patients rescheduled")
#         return state


# compliance agent mock - returns dummy compliance data
class MockComplianceAgent:    
    
    async def validate_compliance(self, state):
        print(f"Compliance Agent validating actions for shipment {state['shipment_id']}")
        
        await asyncio.sleep(0.3)
        
        risk_score = state['risk_assessment']['score']
        
        state['compliance_check'] = {
            'compliant': True,
            'regulations_checked': [
                'GDP 5.2.3 - Temperature Excursion Handling',
                'FDA 21CFR11 - Electronic Records',
                'EU GDP Annex 1 - Quality Management'
            ],
            'violations': [],
            'warnings': [
                'Temperature excursion >30min requires deviation report within 24hr'
            ] if state['minutes_outside_range'] > 30 else [],
            'human_approval_required': risk_score > 70,
            'approval_reason': f'Risk score {risk_score} exceeds threshold' if risk_score > 70 else None,
            'audit_trail_generated': True
        }
        
        state['human_approval_required'] = state['compliance_check']['human_approval_required']
        
        print(f"Compliance check: {'PASS' if state['compliance_check']['compliant'] else 'FAIL'}")
        print(f"Human approval required: {state['human_approval_required']}")
        
        return state


# action agent mock - returns dummy action data
class MockActionAgent:
    async def execute_actions(self, state):
        print(f"Action Agent executing approved actions")
        
        await asyncio.sleep(0.5)
        
        actions = []
        
        # inventory actions
        if state.get('inventory_actions', {}).get('reorder_triggered'):
            actions.append({
                'action_type': 'emergency_reorder',
                'status': 'confirmed',
                'cost': state['inventory_actions']['financial_impact']['reorder_cost'],
                'confirmation_number': 'PO-2026-MOCK-001'
            })
        
        if state.get('inventory_actions', {}).get('reallocation_plan'):
            actions.append({
                'action_type': 'inventory_reallocation',
                'status': 'confirmed',
                'tracking_number': 'MEX-2026-MOCK-002',
                'cost': state['inventory_actions']['financial_impact']['reallocation_cost']
            })
        
        state['actions_taken'] = actions
        
        print(f"Executed {len(actions)} actions")
        return state

# notification agent mock - returns dummy notification data
class MockNotificationAgent:
    async def send_notifications(self, state):
        print(f"Notification Agent sending alerts to {len(state.get('prioritized_facilities', []))} facilities")
        
        await asyncio.sleep(0.5)
        
        notifications = []
        
        for facility in state.get('prioritized_facilities', []):
            notifications.append({
                'facility_id': facility['facility_id'],
                'channel': facility['contact_method'],
                'status': 'delivered',
                'timestamp': state['detected_at'],
                'acknowledged': True
            })
        
        state['notifications_sent'] = notifications
        
        print(f"Sent {len(notifications)} notifications")
        return state