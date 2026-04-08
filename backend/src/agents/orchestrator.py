import asyncio
from datetime import datetime, timezone
from typing import Dict, Any
from langgraph.graph import StateGraph, END

# state models
from src.models.state import OrchestratorState, AnomalyType

# mock agents - replace later with real agents
from src.agents.mocks import MockHospitalPriorityAgent, MockInventoryAgent, MockComplianceAgent, MockNotificationAgent, MockActionAgent

class OrchestratorAgent:

    def __init__(self):
        self.hospital_priority_agent = MockHospitalPriorityAgent()
        self.inventory_agent = MockInventoryAgent()
        self.compliance_agent = MockComplianceAgent()
        self.notification_agent = MockNotificationAgent()
        self.action_agent = MockActionAgent()
        
        # build workflow
        self.workflow = self.build_workflow()
        self.app = self.workflow.compile()

    # node functions for each agent
    
    async def hospital_priority_node(self, state):
        print("\nInvoking hospital priority agent")
        state['updated_at'] = datetime.now(timezone.utc).isoformat()

        updated_state = await self.hospital_priority_agent.score_facilities(state)

        return {
            'prioritized_facilities': updated_state.get('prioritized_facilities')
        }
    
    async def inventory_node(self, state):
        print("\nInvoking inventory management agent")
        state['updated_at'] = datetime.now(timezone.utc).isoformat()
        updated_state = await self.inventory_agent.manage_inventory(state)
    
        return {
            # 'updated_at': datetime.now(timezone.utc).isoformat(),
            'inventory_actions': updated_state.get('inventory_actions')
        }
    
    async def compliance_node(self, state):
        print("\nInvoking compliance agent")
        state['updated_at'] = datetime.now(timezone.utc).isoformat()
        updated_state = await self.compliance_agent.validate_compliance(state)
    
        return {
            'compliance_check': updated_state.get('compliance_check'),
            'human_approval_required': updated_state.get('human_approval_required', False)
        }
    
    async def human_approval_node(self, state):
        print("\nAwaiting human approval")
        print(f"Risk Score: {state['risk_assessment']['score']}")
        print(f"Reason: {state['compliance_check']['approval_reason']}")
        
        # in production system - pause and wait for human input
        # testing - auto-approve after delay
        await asyncio.sleep(1.0)
        
        state['human_approved'] = True
        state['approval_timestamp'] = datetime.now(timezone.utc).isoformat()
        print("Approval received")

        return {
            'human_approved': True,
            'approval_timestamp': datetime.now(timezone.utc).isoformat(),
        }
        
    async def action_node(self, state):
        print("\nInvoking action execution agent")
        state['updated_at'] = datetime.now(timezone.utc).isoformat()
        updated_state = await self.action_agent.execute_actions(state)
    
        return {
            'actions_taken': updated_state.get('actions_taken', [])
        }
    
    async def notification_node(self, state):
        print("\nInvoking notification agent")
        state['updated_at'] = datetime.now(timezone.utc).isoformat()
        updated_state = await self.notification_agent.send_notifications(state)
    
        return {
            'notifications_sent': updated_state.get('notifications_sent', [])
        }
        
    # determine if human approval is needed
    def needs_approval_router(self, state):
        if state.get('human_approval_required', False):
            return "needs_approval"
        return "auto_approve"

    def build_workflow(self):

        workflow = StateGraph(OrchestratorState)
        
        # add nodes/agents
        workflow.add_node("hospital_prioritization", self.hospital_priority_node)
        workflow.add_node("inventory_management", self.inventory_node)
        workflow.add_node("compliance_validation", self.compliance_node)
        workflow.add_node("await_human_approval", self.human_approval_node)
        workflow.add_node("execute_actions", self.action_node)
        workflow.add_node("send_notifications", self.notification_node) 

        # entry point
        workflow.set_entry_point("hospital_prioritization")


        # workflow sequence
        workflow.add_edge("hospital_prioritization", "inventory_management")
        workflow.add_edge("inventory_management", "compliance_validation")

        # conditional routing to decide if approval is needed
        workflow.add_conditional_edges(
            "compliance_validation", 
            self.needs_approval_router,
            {
                "needs_approval": "await_human_approval",
                "auto_approve": "execute_actions"
            }
        )

        # continue workflow sequence
        workflow.add_edge("compliance_validation", "await_human_approval")
        workflow.add_edge("await_human_approval", "execute_actions")
        workflow.add_edge("execute_actions", "send_notifications")
        workflow.add_edge("send_notifications", END)
        
        return workflow

    # invokes orchestration workflow
    async def invoke(self, initial_state):
        # TODO: modify according to the intial state passed by upstream
        print(f"Starting workflow for shipment {initial_state['shipment_id']}")
        print(f"Anomaly: {initial_state['anomaly_type']}")
        print(f"Risk Score: {initial_state['risk_assessment']['score']}")
        
        # workflow metadata
        initial_state['workflow_id'] = f"WF-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        initial_state['created_at'] = datetime.now(timezone.utc).isoformat()
        initial_state['updated_at'] = datetime.now(timezone.utc).isoformat()
        
        # execute the workflow
        final_state = await self.app.ainvoke(initial_state)
        
        print(f"Workflow is complete, actions taken: {len(final_state.get('actions_taken', []))}")
        print(f"Notifications sent: {len(final_state.get('notifications_sent', []))}")
        
        return final_state