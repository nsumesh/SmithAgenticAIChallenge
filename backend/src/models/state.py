"""Backend state models - matches shared/types/agent-state.ts"""
from typing import TypedDict, Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class AnomalyType(str, Enum):
    """Types of anomalies detected"""
    TEMPERATURE_EXCURSION = "temperature_excursion"
    DELAY_CASCADE = "delay_cascade"
    SHOCK_EVENT = "shock_event"
    MISSED_CHECKPOINT = "missed_checkpoint"
    BATTERY_FAILURE = "battery_failure"
    COMPOUND_RISK = "compound_risk"


class TransitPhase(str, Enum):
    """Transit phases from dataset"""
    LOADING_ZONE = "loading_zone"
    AIR_HANDOFF = "air_handoff"
    CUSTOMS_CLEARANCE = "customs_clearance"
    COLD_STORE_TRANSFER = "cold_store_transfer"
    ROAD_TRANSIT = "road_transit"
    SEA_TRANSIT = "sea_transit"
    LAST_MILE = "last_mile"


class RiskAssessment(TypedDict):
    """Output from Risk Assessment Agent"""
    score: int  # 0-100
    spoilage_probability: float  # 0.0-1.0
    confidence: str  # "low", "medium", "high"
    reasoning: str
    trigger_orchestrator: bool
    recommended_urgency: str  # "immediate", "high", "medium", "low"
    breakdown: Dict[str, Any]


class FacilityPriority(TypedDict):
    """Hospital priority scoring output"""
    facility_id: str
    facility_name: str
    priority_score: float  # 0-100
    urgency_breakdown: Dict[str, float]
    contact_method: str  # "erp_webhook", "voice_ivr", "sms"
    patients_affected: int
    critical_patients: int


class InventoryAction(TypedDict):
    """Inventory management decisions"""
    backup_available: bool
    backup_location: Optional[str]
    reorder_triggered: bool
    reallocation_plan: Optional[Dict[str, Any]]
    financial_impact: Dict[str, float]


class ComplianceCheck(TypedDict):
    """Compliance validation results"""
    compliant: bool
    regulations_checked: List[str]
    violations: List[str]
    warnings: List[str]
    human_approval_required: bool
    approval_reason: Optional[str]
    audit_trail_generated: bool


class NotificationResult(TypedDict):
    """Notification delivery results"""
    facility_id: str
    channel: str
    status: str  # "delivered", "failed", "pending"
    timestamp: str
    acknowledged: bool


class OrchestratorState(TypedDict):
    """
    Main state object passed between agents in LangGraph workflow
    This matches the TypeScript OrchestratorState in shared/types/agent-state.ts
    """
    # Core identifiers
    shipment_id: str
    container_id: str
    product_id: str
    
    # Trigger information
    anomaly_type: AnomalyType
    detected_at: str  # ISO timestamp
    
    # Current shipment state
    current_temp_c: float
    temp_slope_c_per_hr: float
    current_delay_min: float
    transit_phase: TransitPhase
    minutes_outside_range: int
    
    # Risk assessment (from Monitoring & Risk Agent)
    risk_assessment: RiskAssessment
    
    # Agent outputs (filled during workflow)
    prioritized_facilities: Optional[List[FacilityPriority]]
    inventory_actions: Optional[InventoryAction]
    appointment_coordination: Optional[Dict[str, Any]]
    compliance_check: Optional[ComplianceCheck]
    route_options: Optional[List[Dict[str, Any]]]  # Optional route agent
    
    # Execution tracking
    actions_taken: List[Dict[str, Any]]
    notifications_sent: List[NotificationResult]
    
    # Human approval
    human_approval_required: bool
    human_approved: Optional[bool]
    approval_timestamp: Optional[str]
    
    # Audit
    workflow_id: str
    created_at: str
    updated_at: str