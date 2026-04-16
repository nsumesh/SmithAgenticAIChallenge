# Notification models for pharmaceutical cold chain monitoring
from pydantic import BaseModel, Field, EmailStr
from typing import List, Dict, Optional, Literal
from datetime import datetime
from enum import Enum

class NotificationSeverity(str, Enum):
    """Severity levels based on risk and regulatory requirements"""
    CRITICAL = "CRITICAL" 
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

class NotificationChannel(str, Enum):
    """Available notification delivery channels"""
    EMAIL = "email"
    SMS = "sms"
    SLACK = "slack"
    WEBHOOK = "webhook"
    PUSH = "push_notification"
    DASHBOARD = "dashboard_update"

class RecipientRole(str, Enum):
    """Stakeholder roles in pharmaceutical supply chain"""
    DIRECTOR = "director"
    QA_MANAGER = "qa_manager"
    LOGISTICS_OPS = "logistics_ops"
    HOSPITAL_ADMIN = "hospital_admin"
    PHARMACY_DIRECTOR = "pharmacy_director"
    PATIENT = "patient"
    REGULATORY_AUTHORITY = "regulatory_authority"

class NotificationStatus(str, Enum):
    """Delivery status tracking"""
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    ACTION_TAKEN = "action_taken"
    FAILED = "failed"
    RETRYING = "retrying"

class Recipient(BaseModel):
    """Notification recipient details"""
    recipient_id: str = Field(..., description="Unique recipient identifier")
    role: RecipientRole
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    sms: Optional[str] = None
    slack_handle: Optional[str] = None
    facility_id: Optional[str] = None
    priority: str = Field(default="NORMAL", description="URGENT, HIGH, NORMAL, LOW")
    on_call: bool = Field(default=False, description="Currently on-call for escalations")

class NotificationContent(BaseModel):
    """Structured notification content"""
    subject: str = Field(..., max_length=200)
    summary: str = Field(..., description="Brief one-line summary")
    body: str = Field(..., description="Full message body")
    action_required: Optional[str] = None
    action_deadline: Optional[datetime] = None
    action_url: Optional[str] = None
    regulatory_citations: List[str] = Field(default_factory=list)
    attachments: List[Dict] = Field(default_factory=list)

class SentNotification(BaseModel):
    """Record of a sent notification"""
    notification_id: str
    channel: NotificationChannel
    recipient: Recipient
    content: NotificationContent
    severity: NotificationSeverity
    sent_at: datetime
    delivered_at: Optional[datetime] = None
    read_at: Optional[datetime] = None
    action_taken_at: Optional[datetime] = None
    status: NotificationStatus
    delivery_metadata: Dict = Field(default_factory=dict)
    retry_count: int = Field(default=0)
    error_message: Optional[str] = None

class EscalationTier(BaseModel):
    """Escalation tier configuration"""
    tier: int
    delay_minutes: int
    target_role: RecipientRole
    channels: List[NotificationChannel]
    message_prefix: str = ""

class NotificationInput(BaseModel):
    """Input from orchestrator to notification agent"""
    # Shipment context
    shipment_id: str
    container_id: str
    window_id: str
    product_category: str
    current_temp_c: float
    minutes_outside_range: int
    transit_phase: str
    
    # Risk assessment
    risk_score: int
    risk_tier: str
    spoilage_probability: float
    
    # Compliance results
    compliance_status: str
    violations: List[Dict] = Field(default_factory=list)
    human_approval_required: bool
    approval_level: Optional[str] = None
    product_disposition: str
    
    # Impact
    affected_facilities: List[str] = Field(default_factory=list)
    critical_patients_affected: int = 0
    at_risk_value: float = 0.0
    backup_available: bool = False
    
    # Timing
    estimated_arrival: Optional[datetime] = None
    current_delay_min: float = 0.0
    
    # Additional context
    regulatory_tags: List[str] = Field(default_factory=list)
    event_type: str = "risk_assessment"

class NotificationOutput(BaseModel):
    """Output from notification agent"""
    notification_batch_id: str
    created_at: datetime
    
    # Summary
    total_notifications: int
    successful_deliveries: int
    failed_deliveries: int
    pending_deliveries: int
    
    # Detailed notifications
    notifications_sent: List[SentNotification]
    
    # Escalation tracking
    escalation_required: bool
    escalation_tier: Optional[int] = None
    escalation_deadline: Optional[datetime] = None
    next_escalation_at: Optional[datetime] = None
    
    # Regulatory compliance
    regulatory_notifications_sent: bool
    notification_audit_trail: List[Dict] = Field(default_factory=list)
    
    # Follow-up
    follow_up_scheduled: bool = False
    follow_up_time: Optional[datetime] = None
    follow_up_action: Optional[str] = None
    
    # Metadata
    agent_version: str = "1.0.0"
    processing_duration_ms: int = 0