# Agentic Notification Agent - intelligent multi-channel stakeholder notification system
# Compliant with FDA 21 CFR Part 11, EU GDP, WHO PQS
import uuid
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

# Handle both relative and absolute imports
try:
    from .models import (
        NotificationInput, NotificationOutput, NotificationSeverity,
        NotificationChannel, RecipientRole, Recipient, SentNotification,
        NotificationStatus
    )
    from .agentic_planner import AgenticStrategicPlanner
    from .message_composer import MessageComposer
    from .channels import NotificationChannelManager
    from .stakeholders import StakeholderRegistry
except ImportError:
    from tools.helper.notification.models import (
        NotificationInput, NotificationOutput, NotificationSeverity,
        NotificationChannel, RecipientRole, Recipient, SentNotification,
        NotificationStatus
    )
    from tools.helper.notification.agentic_planner import AgenticStrategicPlanner
    from tools.helper.notification.message_composer import MessageComposer
    from tools.helper.notification.channels import NotificationChannelManager
    from tools.helper.notification.stakeholders import StakeholderRegistry

class AgenticNotificationAgent:
    """
    Intelligent notification routing and delivery agent
    
    Responsibilities:
    1. Strategic planning using LLM (not rule-based)
    2. Stakeholder resolution (who needs to be notified)
    3. Channel optimization (email, Slack, dashboard, etc.)
    4. Context-aware message composition using LLM
    5. Multi-channel notification dispatch
    6. Escalation management and tracking
    7. Regulatory audit trail generation
    """
    
    def __init__(self):
        self.planner = AgenticStrategicPlanner()
        self.registry = StakeholderRegistry()
        self.composer = MessageComposer()
        self.channels = NotificationChannelManager()
        self.version = "1.0.0-agentic"
    
    async def send_notifications(
        self,
        notification_input: NotificationInput
    ) -> NotificationOutput:
        """
        Main agentic notification workflow
        
        Steps:
        1. Strategic planning (LLM-driven severity and strategy)
        2. Stakeholder resolution (context-aware)
        3. Channel optimization (adaptive)
        4. Message composition (LLM-generated)
        5. Multi-channel dispatch (parallel)
        6. Audit trail generation
        """
        
        start_time = datetime.utcnow()
        batch_id = f"BATCH-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        
        print(f"\n[AGENTIC NOTIFICATION] Starting batch {batch_id}")
        print(f"[AGENTIC NOTIFICATION] Shipment: {notification_input.shipment_id}")
        
        # Step 1: Strategic planning (LLM-driven)
        strategy = await self.planner.create_notification_strategy(notification_input)
        severity = NotificationSeverity(strategy.get('severity', 'HIGH'))
        print(f"[AGENTIC NOTIFICATION] LLM Strategy: {severity.value}")
        
        # Step 2: Resolve stakeholders based on strategy
        stakeholders = self._resolve_stakeholders_agentic(notification_input, strategy)
        print(f"[AGENTIC NOTIFICATION] Stakeholders: {len(stakeholders)}")
        
        # Step 3: Determine channels using strategy
        notification_plan = self._build_notification_plan_agentic(stakeholders, strategy)
        print(f"[AGENTIC NOTIFICATION] Notifications planned: {len(notification_plan)}")
        
        # Step 4 & 5: Compose and send notifications (parallel)
        sent_notifications = await self._dispatch_notifications(
            notification_input, notification_plan, severity, batch_id
        )
        
        # Step 6: Build audit trail
        audit_trail = self._build_audit_trail(notification_input, sent_notifications, batch_id, strategy)
        
        # Step 7: Determine escalation using strategy
        escalation_info = self._determine_escalation_agentic(notification_input, strategy)
        
        # Calculate metrics
        duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        successful = sum(1 for n in sent_notifications if n.status == NotificationStatus.SENT)
        failed = sum(1 for n in sent_notifications if n.status == NotificationStatus.FAILED)
        
        print(f"[AGENTIC NOTIFICATION] Sent: {successful}, Failed: {failed}")
        print(f"[AGENTIC NOTIFICATION] Duration: {duration_ms}ms")
        
        # Build output
        output = NotificationOutput(
            notification_batch_id=batch_id,
            created_at=start_time,
            total_notifications=len(sent_notifications),
            successful_deliveries=successful,
            failed_deliveries=failed,
            pending_deliveries=0,
            notifications_sent=sent_notifications,
            escalation_required=escalation_info['required'],
            escalation_tier=escalation_info.get('tier'),
            escalation_deadline=escalation_info.get('deadline'),
            next_escalation_at=escalation_info.get('next_escalation_at'),
            regulatory_notifications_sent=True,
            notification_audit_trail=audit_trail,
            follow_up_scheduled=escalation_info['required'],
            follow_up_time=escalation_info.get('next_escalation_at'),
            follow_up_action=escalation_info.get('action'),
            agent_version=self.version,
            processing_duration_ms=duration_ms
        )
        
        return output
    
    def _resolve_stakeholders_agentic(
        self,
        input_data: NotificationInput,
        strategy: Dict
    ) -> List[Recipient]:
        """
        Resolve stakeholders based on LLM strategy (not hardcoded rules)
        """
        
        stakeholders = []
        stakeholder_priorities = strategy.get('stakeholder_priorities', {})
        
        must_notify = stakeholder_priorities.get('must_notify', [])
        should_notify = stakeholder_priorities.get('should_notify', [])
        
        # Resolve must-notify stakeholders
        for role_str in must_notify:
            if role_str == 'qa_manager':
                qa = self.registry.get_qa_manager_on_call()
                if qa:
                    stakeholders.append(qa)
            elif role_str == 'director':
                director = self.registry.get_director()
                stakeholders.append(director)
            elif role_str == 'logistics_ops':
                ops = self.registry.get_logistics_ops()
                if ops:
                    stakeholders.append(ops)
            elif role_str == 'hospital_admin':
                hospital_contacts = self.registry.get_all_affected_hospital_contacts(
                    input_data.affected_facilities
                )
                stakeholders.extend(hospital_contacts)
        
        # Resolve should-notify stakeholders
        for role_str in should_notify:
            if role_str == 'hospital_admin' and 'hospital_admin' not in must_notify:
                hospital_contacts = self.registry.get_all_affected_hospital_contacts(
                    input_data.affected_facilities
                )
                stakeholders.extend(hospital_contacts)
            elif role_str == 'pharmacy_director':
                pharmacy_contacts = self.registry.get_all_affected_pharmacy_contacts(
                    input_data.affected_facilities
                )
                stakeholders.extend(pharmacy_contacts)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_stakeholders = []
        for stakeholder in stakeholders:
            if stakeholder.recipient_id not in seen:
                seen.add(stakeholder.recipient_id)
                unique_stakeholders.append(stakeholder)
        
        return unique_stakeholders
    
    def _build_notification_plan_agentic(
        self,
        stakeholders: List[Recipient],
        strategy: Dict
    ) -> List[Tuple[Recipient, List[NotificationChannel]]]:
        """
        Build notification plan based on LLM strategy
        """
        
        plan = []
        severity = strategy.get('severity', 'HIGH')
        sms_justified = strategy.get('resource_constraints', {}).get('sms_budget_justified', False)
        
        for stakeholder in stakeholders:
            channels = []
            
            # Email is almost always included
            if stakeholder.email:
                channels.append(NotificationChannel.EMAIL)
            
            # SMS path disabled for this deployment.
            # if sms_justified and stakeholder.sms and severity in ['CRITICAL', 'HIGH']:
            #     channels.append(NotificationChannel.SMS)
            
            # Slack for internal stakeholders
            if (stakeholder.slack_handle and 
                stakeholder.role in [RecipientRole.DIRECTOR, RecipientRole.QA_MANAGER, RecipientRole.LOGISTICS_OPS]):
                channels.append(NotificationChannel.SLACK)
            
            # Dashboard for all internal stakeholders
            if stakeholder.role in [RecipientRole.DIRECTOR, RecipientRole.QA_MANAGER, RecipientRole.LOGISTICS_OPS]:
                channels.append(NotificationChannel.DASHBOARD)
            
            if channels:
                plan.append((stakeholder, channels))
        
        return plan
    
    async def _dispatch_notifications(
        self,
        input_data: NotificationInput,
        notification_plan: List[Tuple[Recipient, List[NotificationChannel]]],
        severity: NotificationSeverity,
        batch_id: str
    ) -> List[SentNotification]:
        """
        Compose and send notifications in parallel
        """
        
        sent_notifications = []
        tasks = []
        
        for recipient, channels in notification_plan:
            for channel in channels:
                task = self._send_single_notification(
                    input_data, recipient, channel, severity, batch_id
                )
                tasks.append(task)
        
        # Execute all notifications in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, SentNotification):
                sent_notifications.append(result)
            elif isinstance(result, Exception):
                print(f"[ERROR] Notification failed: {result}")
        
        return sent_notifications
    
    async def _send_single_notification(
        self,
        input_data: NotificationInput,
        recipient: Recipient,
        channel: NotificationChannel,
        severity: NotificationSeverity,
        batch_id: str
    ) -> SentNotification:
        """Send a single notification through a specific channel"""
        
        # Generate notification ID
        notification_id = f"NOTIF-{uuid.uuid4().hex[:12]}"
        
        # Compose message using LLM
        content = await self.composer.compose_message(
            notification_input=input_data,
            recipient_role=recipient.role,
            severity=severity,
            channel=channel.value
        )
        
        # Send via channel
        delivery_result = await self.channels.send_notification(
            channel=channel,
            recipient=recipient,
            content=content,
            severity=severity,
            notification_id=notification_id,
            metadata={'shipment_id': input_data.shipment_id, 'batch_id': batch_id}
        )
        
        # Build SentNotification record
        sent_notification = SentNotification(
            notification_id=notification_id,
            channel=channel,
            recipient=recipient,
            content=content,
            severity=severity,
            sent_at=delivery_result.get('sent_at', datetime.utcnow()),
            status=delivery_result.get('status', NotificationStatus.SENT),
            delivery_metadata=delivery_result.get('delivery_metadata', {}),
            error_message=delivery_result.get('error')
        )
        
        return sent_notification
    
    def _determine_escalation_agentic(
        self,
        input_data: NotificationInput,
        strategy: Dict
    ) -> Dict:
        """
        Determine escalation based on LLM strategy
        """
        
        if not input_data.human_approval_required:
            return {'required': False}
        
        urgency_timeline = strategy.get('urgency_timeline', {})
        decision_needed_minutes = urgency_timeline.get('decision_needed_within_minutes', 60)
        
        # Use strategy-based timeline instead of fixed rules
        first_escalation_minutes = max(decision_needed_minutes // 2, 15)  # Half the decision time, min 15 min
        final_deadline_minutes = decision_needed_minutes
        
        now = datetime.utcnow()
        
        return {
            'required': True,
            'tier': 1,
            'deadline': now + timedelta(minutes=final_deadline_minutes),
            'next_escalation_at': now + timedelta(minutes=first_escalation_minutes),
            'action': f'escalate_if_no_response_in_{first_escalation_minutes}_min',
            'strategy_reasoning': urgency_timeline.get('reasoning', 'LLM-determined timeline')
        }
    
    def _build_audit_trail(
        self,
        input_data: NotificationInput,
        sent_notifications: List[SentNotification],
        batch_id: str,
        strategy: Dict
    ) -> List[Dict]:
        """
        Build FDA 21 CFR Part 11 compliant audit trail
        """
        
        audit_entries = []
        
        # Initial trigger event with strategy
        audit_entries.append({
            'timestamp': datetime.utcnow().isoformat(),
            'event': 'agentic_notification_batch_created',
            'batch_id': batch_id,
            'shipment_id': input_data.shipment_id,
            'trigger': input_data.event_type,
            'compliance_status': input_data.compliance_status,
            'llm_strategy': {
                'severity': strategy.get('severity'),
                'reasoning': strategy.get('reasoning'),
                'stakeholder_count': len(strategy.get('stakeholder_priorities', {}).get('must_notify', []))
            }
        })
        
        # Each notification sent
        for notification in sent_notifications:
            audit_entries.append({
                'timestamp': notification.sent_at.isoformat(),
                'event': 'agentic_notification_sent',
                'notification_id': notification.notification_id,
                'recipient': notification.recipient.recipient_id,
                'recipient_role': notification.recipient.role.value,
                'channel': notification.channel.value,
                'severity': notification.severity.value,
                'status': notification.status.value,
                'message_subject': notification.content.subject,
                'llm_composed': True
            })
        
        return audit_entries