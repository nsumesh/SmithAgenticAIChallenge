# Agentic Strategic Planner for Notification System
import os
import json
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from groq import AsyncGroq
from dotenv import load_dotenv

# Handle both relative and absolute imports
try:
    from .models import NotificationInput, NotificationSeverity
except ImportError:
    from tools.helper.notification.models import NotificationInput, NotificationSeverity

load_dotenv()

class AgenticStrategicPlanner:
    """
    LLM-driven strategic planning for notification decisions
    Makes autonomous decisions about:
    1. Overall notification strategy
    2. Urgency assessment (context-aware, not just rules)
    3. Risk prioritization
    4. Resource allocation (SMS budget vs urgency)
    """
    
    def __init__(self):
        api_key = os.getenv('GROQ_API_KEY')
        if not api_key:
            raise ValueError("GROQ_API_KEY not found in environment")
        
        self.llm = AsyncGroq(api_key=api_key)
        self.model = "llama-3.1-8b-instant"
    
    async def create_notification_strategy(
        self,
        notification_input: NotificationInput,
        context: Optional[Dict] = None
    ) -> Dict:
        """Analyze situation and create strategic notification plan"""
        
        # Build context
        current_time = datetime.utcnow()
        day_of_week = current_time.strftime("%A")
        hour = current_time.hour
        
        # Determine if business hours (M-F 8am-6pm UTC)
        is_business_hours = (
            current_time.weekday() < 5 and  # Monday-Friday
            8 <= hour < 18
        )
        
        # Build prompt for strategic planning
        prompt = self._build_strategy_prompt(
            notification_input,
            current_time,
            day_of_week,
            is_business_hours,
            context or {}
        )
        
        try:
            response = await self.llm.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": self._get_system_prompt()
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.2,  # Some creativity but mostly logical
                max_tokens=1500,
                response_format={"type": "json_object"}
            )
            
            strategy = json.loads(response.choices[0].message.content)
            
            print(f"[AGENTIC PLANNER] Strategy created")
            print(f"[AGENTIC PLANNER] Severity: {strategy.get('severity')}")
            print(f"[AGENTIC PLANNER] Reasoning: {strategy.get('reasoning')[:100]}...")
            
            return strategy
            
        except Exception as e:
            print(f"[ERROR] Strategic planning failed: {e}")
            # Fallback to conservative strategy
            return self._fallback_strategy(notification_input)
    
    def _get_system_prompt(self) -> str:
        """System prompt for strategic planner"""
        return """You are a strategic notification planner for pharmaceutical cold chain logistics.

Your role is to analyze critical shipment situations and design optimal notification strategies that:
1. Ensure patient safety (top priority)
2. Meet regulatory requirements (FDA, EU GDP, WHO)
3. Minimize alert fatigue
4. Optimize resource usage (SMS costs vs urgency)
5. Consider stakeholder availability and response patterns

Key principles:
- Patient safety > Cost optimization
- Regulatory compliance is non-negotiable
- Consider time-of-day and stakeholder availability
- Learn from historical response patterns
- Balance urgency with avoiding alert fatigue

You must provide clear reasoning for every decision."""
    
    def _build_strategy_prompt(
        self,
        input_data: NotificationInput,
        current_time: datetime,
        day_of_week: str,
        is_business_hours: bool,
        context: Dict
    ) -> str:
        """Build detailed prompt for strategy creation"""
        
        prompt = f"""Analyze this pharmaceutical shipment situation and create a notification strategy.

SHIPMENT SITUATION:
- Shipment ID: {input_data.shipment_id}
- Product: {input_data.product_category}
- Temperature: {input_data.current_temp_c}°C
- Duration Outside Range: {input_data.minutes_outside_range} minutes
- Transit Phase: {input_data.transit_phase}

RISK ASSESSMENT:
- Risk Tier: {input_data.risk_tier}
- Risk Score: {input_data.risk_score}/100
- Spoilage Probability: {input_data.spoilage_probability * 100:.1f}%

COMPLIANCE STATUS:
- Compliance: {input_data.compliance_status}
- Violations: {len(input_data.violations)}
- Human Approval Required: {input_data.human_approval_required}
- Approval Level: {input_data.approval_level}
- Product Disposition: {input_data.product_disposition}

IMPACT ANALYSIS:
- Critical Patients Affected: {input_data.critical_patients_affected}
- Affected Facilities: {len(input_data.affected_facilities)} ({', '.join(input_data.affected_facilities[:3])})
- Financial At-Risk: ${input_data.at_risk_value:,.0f}
- Backup Available: {input_data.backup_available}
- Current Delay: {input_data.current_delay_min:.0f} minutes

TIMING CONTEXT:
- Current Time: {current_time.strftime('%Y-%m-%d %H:%M UTC')}
- Day: {day_of_week}
- Business Hours: {is_business_hours}
- Estimated Arrival: {input_data.estimated_arrival.strftime('%Y-%m-%d %H:%M') if input_data.estimated_arrival else 'Unknown'}

REGULATORY TAGS:
{', '.join(input_data.regulatory_tags)}

HISTORICAL CONTEXT (if available):
{json.dumps(context.get('historical_patterns', {}), indent=2)}

QUESTION:
Design an optimal notification strategy considering:
1. Severity assessment (is this truly CRITICAL, HIGH, MEDIUM, or LOW?)
2. Urgency timeline (how fast do we need decisions?)
3. Stakeholder prioritization (who can actually help vs who just needs to know?)
4. Resource allocation (when is SMS cost justified?)
5. Risk mitigation priorities (patient safety, regulatory compliance, financial)

Respond with JSON:
{{
  "severity": "CRITICAL|HIGH|MEDIUM|LOW",
  "reasoning": "2-3 sentences explaining severity assessment with specific factors",
  "urgency_timeline": {{
    "decision_needed_within_minutes": 30,
    "reasoning": "why this timeline"
  }},
  "priority_objectives": [
    "patient_safety",
    "regulatory_compliance",
    "financial_protection"
  ],
  "resource_constraints": {{
    "sms_budget_justified": true,
    "reasoning": "when SMS cost is worth it"
  }},
  "stakeholder_priorities": {{
    "must_notify": ["role1", "role2"],
    "should_notify": ["role3"],
    "optional": ["role4"],
    "reasoning": "why these priorities"
  }},
  "special_considerations": [
    "after hours - expect slower response",
    "biologics require director approval per WHO PQS"
  ]
}}
"""
        
        return prompt
    
    def _fallback_strategy(self, input_data: NotificationInput) -> Dict:
        """Conservative fallback if LLM fails"""
        
        # Conservative: Treat as HIGH severity by default
        return {
            "severity": "HIGH",
            "reasoning": "LLM planning failed, using conservative fallback strategy",
            "urgency_timeline": {
                "decision_needed_within_minutes": 60,
                "reasoning": "Conservative default timeline"
            },
            "priority_objectives": [
                "patient_safety",
                "regulatory_compliance"
            ],
            "resource_constraints": {
                "sms_budget_justified": True,
                "reasoning": "Conservative approach when uncertain"
            },
            "stakeholder_priorities": {
                "must_notify": ["qa_manager", "director"],
                "should_notify": ["hospital_admin"],
                "optional": [],
                "reasoning": "Conservative stakeholder selection"
            },
            "special_considerations": [
                "Fallback mode - notify all critical stakeholders"
            ]
        }