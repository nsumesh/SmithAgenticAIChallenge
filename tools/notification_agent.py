"""
Agentic Notification Agent - LangChain Tool Integration
Intelligent multi-channel stakeholder notification with LLM-driven decision making
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from pathlib import Path

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Import notification components
try:
    from tools.helper.notification.agent import AgenticNotificationAgent
    from tools.helper.notification.models import NotificationInput as AgenticNotificationInput
except ImportError:
    from .helper.notification.agent import AgenticNotificationAgent
    from .helper.notification.models import NotificationInput as AgenticNotificationInput

load_dotenv()

# Global agent instance (reused across calls for performance)
_notification_agent = None

def get_notification_agent() -> AgenticNotificationAgent:
    """Get or create global notification agent instance"""
    global _notification_agent
    if _notification_agent is None:
        _notification_agent = AgenticNotificationAgent()
    return _notification_agent

# LangChain Tool Input Schema (simplified for orchestrator)
class NotificationInput(BaseModel):
    """Input schema for notification tool (orchestrator interface)"""
    shipment_id: str
    container_id: str
    risk_tier: str = Field(description="LOW, MEDIUM, HIGH, or CRITICAL")
    recipients: List[str] = Field(
        description="Recipient roles: ops_team, clinic, hospital, management, regulatory"
    )
    message: str = Field(description="Notification body text")
    channel: str = Field(
        default="dashboard", description="Delivery channel: email, sms, dashboard, webhook"
    )
    # Cascade-enriched fields — populated by _enrich_tool_input() at runtime
    revised_eta: Optional[str] = Field(
        default=None,
        description="Revised arrival ETA (ISO datetime) computed from current_delay_min",
    )
    spoilage_probability: Optional[float] = Field(
        default=None,
        description="ML spoilage probability (0-1) for this window",
    )
    facility_name: Optional[str] = Field(
        default=None,
        description="Destination or backup facility name, injected from cold_storage result",
    )

def _execute(
    shipment_id: str,
    container_id: str,
    risk_tier: str,
    recipients: List[str],
    message: str,
    channel: str = "dashboard",
    revised_eta: Optional[str] = None,
    spoilage_probability: Optional[float] = None,
    facility_name: Optional[str] = None,
) -> dict:
    """
    Execute agentic notification workflow
    
    This function:
    1. Maps orchestrator input to agentic notification input
    2. Runs the agentic notification agent (LLM-driven)
    3. Returns structured results for orchestrator
    """
    
    # Map simple orchestrator input to rich agentic input
    agentic_input = _map_orchestrator_to_agentic_input(
        shipment_id=shipment_id,
        container_id=container_id,
        risk_tier=risk_tier,
        recipients=recipients,
        message=message,
        channel=channel,
        revised_eta=revised_eta,
        spoilage_probability=spoilage_probability,
        facility_name=facility_name
    )
    
    # Execute agentic notification workflow
    notification_result = None
    notification_error = None
    
    try:
        agent = get_notification_agent()
        
        # Run async agent in sync context, including when caller already has an event loop.
        notification_result = _run_async_safely(
            agent.send_notifications(agentic_input)
        )
        
        print(f"[NOTIFICATION TOOL] Agentic workflow completed")
        print(f"[NOTIFICATION TOOL] Sent: {notification_result.successful_deliveries}")
        print(f"[NOTIFICATION TOOL] Failed: {notification_result.failed_deliveries}")
        
    except Exception as e:
        notification_error = str(e)
        print(f"[NOTIFICATION TOOL] Agentic workflow failed: {e}")
    
    # Build orchestrator-compatible response
    if notification_result:
        return {
            "tool": "notification_agent",
            "status": "notifications_sent",
            "shipment_id": shipment_id,
            "container_id": container_id,
            "risk_tier": risk_tier,
            "recipients": recipients,
            "channel": channel,
            
            # Agentic results
            "notification_batch_id": notification_result.notification_batch_id,
            "total_notifications": notification_result.total_notifications,
            "successful_deliveries": notification_result.successful_deliveries,
            "failed_deliveries": notification_result.failed_deliveries,
            "escalation_required": notification_result.escalation_required,
            "escalation_deadline": notification_result.escalation_deadline.isoformat() if notification_result.escalation_deadline else None,
            
            # Notification details
            "notifications_sent": [
                {
                    "notification_id": n.notification_id,
                    "recipient_role": n.recipient.role.value,
                    "recipient_name": n.recipient.name,
                    "channel": n.channel.value,
                    "subject": n.content.subject,
                    "status": n.status.value,
                    "sent_at": n.sent_at.isoformat()
                }
                for n in notification_result.notifications_sent
            ],
            
            # Audit and compliance
            "regulatory_notifications_sent": notification_result.regulatory_notifications_sent,
            "audit_trail_entries": len(notification_result.notification_audit_trail),
            "follow_up_scheduled": notification_result.follow_up_scheduled,
            
            # Metadata
            "agent_version": notification_result.agent_version,
            "processing_duration_ms": notification_result.processing_duration_ms,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agentic_workflow": True
        }
    else:
        # Fallback response if agentic workflow fails
        return {
            "tool": "notification_agent",
            "status": "notification_failed",
            "shipment_id": shipment_id,
            "container_id": container_id,
            "risk_tier": risk_tier,
            "recipients": recipients,
            "channel": channel,
            "error": notification_error,
            "fallback_mode": True,
            "delivered": False,
            "requires_approval": risk_tier in ("HIGH", "CRITICAL"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


def _run_async_safely(coro):
    """
    Run coroutine from sync code safely in both contexts:
    - no running event loop (normal scripts)
    - already-running event loop (async test runners, notebooks)
    """
    try:
        asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result()
    except RuntimeError:
        return asyncio.run(coro)

def _map_orchestrator_to_agentic_input(
    shipment_id: str,
    container_id: str,
    risk_tier: str,
    recipients: List[str],
    message: str,
    channel: str,
    revised_eta: Optional[str] = None,
    spoilage_probability: Optional[float] = None,
    facility_name: Optional[str] = None
) -> AgenticNotificationInput:
    """
    Map simple orchestrator input to rich agentic notification input
    
    The orchestrator provides minimal data, but the agentic agent expects
    comprehensive shipment context. This function enriches the input with
    reasonable defaults and extracted information.
    """
    
    # Extract facility names from recipients and facility_name
    affected_facilities = []
    if facility_name:
        affected_facilities.append(facility_name)
    
    # Map recipient roles to affected facilities
    if "hospital" in recipients or "clinic" in recipients:
        if not affected_facilities:
            affected_facilities = ["General Hospital", "City Medical Center"]
    
    # Estimate compliance status based on risk tier and message
    compliance_status = "compliant"
    violations = []
    if risk_tier in ["HIGH", "CRITICAL"]:
        compliance_status = "violation" if "violation" in message.lower() or "breach" in message.lower() else "borderline"
        if compliance_status == "violation":
            violations = [{"type": "temperature_excursion", "severity": risk_tier}]
    
    # Estimate product category from context
    product_category = "standard_refrigerated"
    if "biologic" in message.lower() or "vaccine" in message.lower():
        product_category = "biologics"
    elif "insulin" in message.lower():
        product_category = "insulin"
    
    # Estimate temperature and duration from message
    current_temp_c = 5.0  # Default safe temperature
    minutes_outside_range = 0
    
    if risk_tier == "CRITICAL":
        current_temp_c = 12.0
        minutes_outside_range = 120
    elif risk_tier == "HIGH":
        current_temp_c = 9.0
        minutes_outside_range = 60
    elif risk_tier == "MEDIUM":
        current_temp_c = 7.0
        minutes_outside_range = 30
    
    # Estimate financial impact
    at_risk_value = 0.0
    if risk_tier == "CRITICAL":
        at_risk_value = 250000.0
    elif risk_tier == "HIGH":
        at_risk_value = 150000.0
    elif risk_tier == "MEDIUM":
        at_risk_value = 75000.0
    
    # Estimate patient impact
    critical_patients_affected = 0
    if risk_tier == "CRITICAL" and product_category == "biologics":
        critical_patients_affected = 25
    elif risk_tier == "HIGH":
        critical_patients_affected = 10
    elif risk_tier == "MEDIUM":
        critical_patients_affected = 5
    
    # Parse revised ETA
    estimated_arrival = None
    if revised_eta:
        try:
            estimated_arrival = datetime.fromisoformat(revised_eta.replace('Z', '+00:00'))
        except:
            pass
    
    # Build comprehensive agentic input
    return AgenticNotificationInput(
        shipment_id=shipment_id,
        container_id=container_id,
        window_id=f"WIN-{shipment_id.split('-')[-1]}" if '-' in shipment_id else f"WIN-{shipment_id}",
        product_category=product_category,
        current_temp_c=current_temp_c,
        minutes_outside_range=minutes_outside_range,
        transit_phase="air_transport",  # Default
        
        # Risk assessment
        risk_score={"LOW": 25, "MEDIUM": 50, "HIGH": 75, "CRITICAL": 95}.get(risk_tier, 50),
        risk_tier=risk_tier,
        spoilage_probability=spoilage_probability or (0.8 if risk_tier == "CRITICAL" else 0.4 if risk_tier == "HIGH" else 0.1),
        
        # Compliance
        compliance_status=compliance_status,
        violations=violations,
        human_approval_required=risk_tier in ["HIGH", "CRITICAL"],
        approval_level="director" if risk_tier == "CRITICAL" else "qa_manager" if risk_tier == "HIGH" else None,
        product_disposition="quarantine" if compliance_status == "violation" else "investigate" if risk_tier in ["HIGH", "CRITICAL"] else "release",
        
        # Impact
        affected_facilities=affected_facilities,
        critical_patients_affected=critical_patients_affected,
        at_risk_value=at_risk_value,
        backup_available=False,  # Conservative default
        
        # Timing
        estimated_arrival=estimated_arrival,
        current_delay_min=30.0 if risk_tier in ["HIGH", "CRITICAL"] else 0.0,
        
        # Context
        regulatory_tags=["GDP", "FDA_21CFR11"] if product_category == "biologics" else ["GDP"],
        event_type="risk_assessment"
    )

# Create LangChain tool
notification_tool = StructuredTool.from_function(
    func=_execute,
    name="notification_agent",
    description=(
        "Send intelligent, context-aware notifications to stakeholders using AI-powered "
        "decision making. Uses LLM to determine optimal notification strategy, "
        "stakeholder selection, channel optimization, and message composition. "
        "Supports multi-channel delivery (email, SMS, Slack, dashboard) with "
        "regulatory compliance and audit trails. Includes escalation management "
        "and adaptive response timelines."
    ),
    args_schema=NotificationInput,
)
