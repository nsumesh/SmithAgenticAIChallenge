# LLM-powered message composition for context-aware notifications
# Generates professional, role-specific messages with regulatory compliance
import os
import json
from typing import Dict, Optional
from groq import AsyncGroq
from dotenv import load_dotenv

# Handle both relative and absolute imports
try:
    from .models import (
        NotificationContent, NotificationSeverity, RecipientRole, NotificationInput
    )
except ImportError:
    from tools.helper.notification.models import (
        NotificationContent, NotificationSeverity, RecipientRole, NotificationInput
    )

load_dotenv()

class MessageComposer:
    """Compose context-aware notification messages using LLM"""
    
    def __init__(self):
        api_key = os.getenv('GROQ_API_KEY')
        if not api_key:
            raise ValueError("GROQ_API_KEY not found in environment")
        
        self.llm = AsyncGroq(api_key=api_key)
        self.model = "llama-3.1-8b-instant"
    
    async def compose_message(
        self,
        notification_input: NotificationInput,
        recipient_role: RecipientRole,
        severity: NotificationSeverity,
        channel: str
    ) -> NotificationContent:
        """Compose role-specific, channel-appropriate message"""
        
        # Build prompt based on role and channel
        prompt = self._build_composition_prompt(
            notification_input, recipient_role, severity, channel
        )
        
        try:
            response = await self.llm.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self._get_system_prompt(recipient_role)},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,  # Some creativity but mostly deterministic
                max_tokens=800,
                response_format={"type": "json_object"}
            )
            
            message_data = json.loads(response.choices[0].message.content)
            
            # Create NotificationContent object
            content = NotificationContent(
                subject=message_data.get('subject', 'Shipment Alert'),
                summary=message_data.get('summary', 'Shipment requires attention'),
                body=message_data.get('body', 'Please review shipment status.'),
                action_required=message_data.get('action_required'),
                action_url=message_data.get('action_url'),
                regulatory_citations=message_data.get('regulatory_citations', [])
            )
            
            return content
            
        except Exception as e:
            print(f"[ERROR] Message composition failed: {e}")
            return self._fallback_message(notification_input, recipient_role, severity)
    
    def _get_system_prompt(self, recipient_role: RecipientRole) -> str:
        """Get role-specific system prompt"""
        
        role_prompts = {
            RecipientRole.DIRECTOR: """You are composing notifications for a pharmaceutical company director. 
            Focus on: strategic impact, regulatory compliance, financial implications, and decision authority needed.
            Tone: Executive summary style, concise but comprehensive.""",
            
            RecipientRole.QA_MANAGER: """You are composing notifications for a QA manager in pharmaceutical logistics.
            Focus on: compliance violations, product disposition decisions, regulatory requirements, and quality impact.
            Tone: Technical and regulatory-focused, action-oriented.""",
            
            RecipientRole.LOGISTICS_OPS: """You are composing notifications for logistics operations team.
            Focus on: immediate actions needed, rerouting options, facility coordination, and timeline impacts.
            Tone: Operational and urgent, clear next steps.""",
            
            RecipientRole.HOSPITAL_ADMIN: """You are composing notifications for hospital administrators.
            Focus on: patient impact, delivery delays, alternative arrangements, and clinical implications.
            Tone: Patient-care focused, professional medical communication.""",
            
            RecipientRole.PHARMACY_DIRECTOR: """You are composing notifications for pharmacy directors.
            Focus on: drug availability, patient safety, inventory management, and clinical alternatives.
            Tone: Clinical and inventory-focused, patient safety priority."""
        }
        
        base_prompt = """You compose professional pharmaceutical supply chain notifications.
        
        Requirements:
        - Clear, actionable communication
        - Regulatory compliance awareness (FDA, EU GDP, WHO)
        - Appropriate urgency level
        - Professional medical/pharmaceutical tone
        - Include relevant regulatory citations when applicable
        
        Always respond with valid JSON containing: subject, summary, body, action_required, action_url, regulatory_citations."""
        
        return role_prompts.get(recipient_role, base_prompt)
    
    def _build_composition_prompt(
        self,
        input_data: NotificationInput,
        recipient_role: RecipientRole,
        severity: NotificationSeverity,
        channel: str
    ) -> str:
        """Build message composition prompt"""
        
        # Channel-specific constraints
        channel_constraints = {
            'sms': "SMS: Max 160 characters, urgent tone, include callback number",
            'email': "Email: Professional format, detailed but concise, include action items",
            'slack': "Slack: Professional operations alert format, no emojis or decorative symbols, clear ownership and actions",
            'dashboard': "Dashboard: Brief summary with key metrics highlighted"
        }
        
        constraint = channel_constraints.get(channel, "Standard professional notification")
        
        prompt = f"""Compose a {severity.value} severity notification for a {recipient_role.value}.

SHIPMENT DETAILS:
- Shipment ID: {input_data.shipment_id}
- Container: {input_data.container_id}
- Product: {input_data.product_category}
- Current Temperature: {input_data.current_temp_c}°C
- Duration Outside Range: {input_data.minutes_outside_range} minutes
- Transit Phase: {input_data.transit_phase}

RISK & COMPLIANCE:
- Risk Tier: {input_data.risk_tier}
- Compliance Status: {input_data.compliance_status}
- Violations: {len(input_data.violations)} found
- Approval Required: {input_data.human_approval_required}
- Approval Level: {input_data.approval_level or 'None'}
- Product Disposition: {input_data.product_disposition}

IMPACT:
- Critical Patients: {input_data.critical_patients_affected}
- Affected Facilities: {', '.join(input_data.affected_facilities) if input_data.affected_facilities else 'None'}
- Financial Risk: ${input_data.at_risk_value:,.0f}
- Backup Available: {input_data.backup_available}

TIMING:
- Current Delay: {input_data.current_delay_min:.0f} minutes
- ETA: {input_data.estimated_arrival.strftime('%Y-%m-%d %H:%M') if input_data.estimated_arrival else 'Unknown'}

CHANNEL REQUIREMENTS:
{constraint}

REGULATORY CONTEXT:
Tags: {', '.join(input_data.regulatory_tags)}

Compose an appropriate notification with:
1. Clear subject line
2. One-sentence summary
3. Detailed body with key information
4. Specific action required (if any)
5. Relevant regulatory citations

Respond with JSON:
{{
  "subject": "Clear, specific subject line",
  "summary": "One sentence summary of the situation",
  "body": "Detailed message body with all relevant information",
  "action_required": "Specific action needed from recipient (or null)",
  "action_url": "URL for taking action (or null)",
  "regulatory_citations": ["FDA 21 CFR 211.142", "EU GDP Guidelines"]
}}
"""
        
        return prompt
    
    def _fallback_message(
        self,
        input_data: NotificationInput,
        recipient_role: RecipientRole,
        severity: NotificationSeverity
    ) -> NotificationContent:
        """Create fallback message if LLM fails"""
        
        return NotificationContent(
            subject=f"{severity.value}: Shipment {input_data.shipment_id} Alert",
            summary=f"Shipment {input_data.shipment_id} requires immediate attention",
            body=f"""
ALERT: {severity.value} risk detected for shipment {input_data.shipment_id}

Product: {input_data.product_category}
Temperature: {input_data.current_temp_c}°C
Duration outside range: {input_data.minutes_outside_range} minutes
Compliance status: {input_data.compliance_status}

Immediate review required.
            """.strip(),
            action_required="Review shipment status and approve disposition" if input_data.human_approval_required else None,
            regulatory_citations=["FDA 21 CFR Part 11", "EU GDP Guidelines"]
        )