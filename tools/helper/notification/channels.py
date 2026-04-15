"""
Multi-channel notification delivery providers
Production: Real integrations (SendGrid, Twilio, Slack)
Hackathon: Mock implementations with realistic logging
"""
import os
import json
import asyncio
from datetime import datetime
from typing import Dict, Optional
from pathlib import Path

# Production imports (install with: pip install aiosmtplib twilio)
try:
    import aiosmtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    SMTP_AVAILABLE = True
except ImportError:
    SMTP_AVAILABLE = False

# Legacy SendGrid support (if needed)
try:
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail
    SENDGRID_AVAILABLE = True
except ImportError:
    SENDGRID_AVAILABLE = False

try:
    from twilio.rest import Client as TwilioClient
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False

try:
    from slack_sdk.web.async_client import AsyncWebClient
    from slack_sdk.errors import SlackApiError
    SLACK_AVAILABLE = True
except ImportError:
    SLACK_AVAILABLE = False

# Handle both relative and absolute imports
try:
    from .models import (
        Recipient, NotificationContent, NotificationChannel, 
        NotificationStatus, SentNotification, NotificationSeverity
    )
except ImportError:
    from tools.helper.notification.models import (
        Recipient, NotificationContent, NotificationChannel, 
        NotificationStatus, SentNotification, NotificationSeverity
    )

# Create logs directory
LOG_DIR = Path(__file__).parent.parent.parent.parent / "notification_logs"
LOG_DIR.mkdir(exist_ok=True)

class EmailProvider:
    """
    Email notification provider
    Production: Gmail SMTP, SendGrid, AWS SES, Mailgun
    Hackathon: Mock with detailed logging
    """
    
    def __init__(self):
        self.provider = os.getenv('EMAIL_PROVIDER', 'mock')
        self.notification_mode = os.getenv('NOTIFICATION_MODE', 'mock')
        self.log_file = LOG_DIR / "email_notifications.jsonl"
        
        # Initialize production clients
        self.gmail_config = None
        self.sendgrid_client = None
        
        # Gmail SMTP setup
        if (self.provider == 'gmail_smtp' and 
            self.notification_mode == 'production' and 
            SMTP_AVAILABLE):
            
            gmail_email = os.getenv('GMAIL_EMAIL')
            gmail_password = os.getenv('GMAIL_APP_PASSWORD')
            
            if (gmail_email and gmail_password and 
                gmail_email != 'your-gmail@gmail.com' and
                gmail_password != 'your_16_character_app_password_here'):
                
                self.gmail_config = {
                    'email': gmail_email,
                    'password': gmail_password,
                    'from_name': os.getenv('GMAIL_FROM_NAME', 'PharmaCold Alert System'),
                    'smtp_server': 'smtp.gmail.com',
                    'smtp_port': 587
                }
                print(f"[EMAIL] Gmail SMTP configured for production ({gmail_email})")
        
        # SendGrid setup (legacy support)
        elif (self.provider == 'sendgrid' and 
              self.notification_mode == 'production' and 
              SENDGRID_AVAILABLE):
            
            api_key = os.getenv('SENDGRID_API_KEY')
            if api_key and api_key != 'your_sendgrid_api_key_here':
                try:
                    self.sendgrid_client = SendGridAPIClient(api_key=api_key)
                    print(f"[EMAIL] SendGrid client initialized for production")
                except Exception as e:
                    print(f"[EMAIL] SendGrid initialization failed: {e}")
    
    async def send(
        self,
        recipient: Recipient,
        content: NotificationContent,
        severity: NotificationSeverity,
        notification_id: str
    ) -> Dict:
        """Send email notification"""
        
        if not recipient.email:
            return {
                'status': NotificationStatus.FAILED,
                'error': 'No email address provided'
            }
        
        # Determine if we should use production or mock
        use_gmail = (
            self.gmail_config is not None and 
            self.notification_mode == 'production'
        )
        
        use_sendgrid = (
            self.sendgrid_client is not None and 
            self.notification_mode == 'production'
        )
        
        if use_gmail:
            return await self._send_gmail_smtp(
                recipient, content, severity, notification_id
            )
        elif use_sendgrid:
            return await self._send_sendgrid_email(
                recipient, content, severity, notification_id
            )
        else:
            return await self._send_mock_email(
                recipient, content, severity, notification_id
            )
    
    async def _send_gmail_smtp(
        self,
        recipient: Recipient,
        content: NotificationContent,
        severity: NotificationSeverity,
        notification_id: str
    ) -> Dict:
        """Send real email via Gmail SMTP"""
        
        try:
            # Create email message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = content.subject
            msg['From'] = f"{self.gmail_config['from_name']} <{self.gmail_config['email']}>"
            msg['To'] = recipient.email
            
            # Create both plain text and HTML versions
            text_part = MIMEText(content.body, 'plain')
            html_part = MIMEText(self._format_html_email(content, severity), 'html')
            
            msg.attach(text_part)
            msg.attach(html_part)
            
            # Send via Gmail SMTP
            await aiosmtplib.send(
                msg,
                hostname=self.gmail_config['smtp_server'],
                port=self.gmail_config['smtp_port'],
                start_tls=True,
                username=self.gmail_config['email'],
                password=self.gmail_config['password']
            )
            
            # Log successful send
            email_payload = {
                'notification_id': notification_id,
                'timestamp': datetime.utcnow().isoformat(),
                'provider': 'gmail_smtp_production',
                'to': recipient.email,
                'from': self.gmail_config['email'],
                'subject': content.subject,
                'severity': severity.value,
                'recipient_role': recipient.role.value,
                'delivery_status': 'sent',
                'smtp_server': self.gmail_config['smtp_server']
            }
            
            with open(self.log_file, 'a') as f:
                f.write(json.dumps(email_payload) + '\n')
            
            print(f"[EMAIL-GMAIL] Sent to {recipient.email}: {content.subject}")
            
            return {
                'status': NotificationStatus.SENT,
                'sent_at': datetime.utcnow(),
                'delivery_metadata': {
                    'provider': 'gmail_smtp_production',
                    'message_id': f"gmail_{notification_id}",
                    'recipient_email': recipient.email,
                    'smtp_server': self.gmail_config['smtp_server']
                }
            }
            
        except Exception as e:
            print(f"[EMAIL-GMAIL] Gmail SMTP send failed: {e}")
            
            # Log the failure
            error_payload = {
                'notification_id': notification_id,
                'timestamp': datetime.utcnow().isoformat(),
                'provider': 'gmail_smtp_production',
                'to': recipient.email,
                'subject': content.subject,
                'delivery_status': 'failed',
                'error': str(e)
            }
            
            with open(self.log_file, 'a') as f:
                f.write(json.dumps(error_payload) + '\n')
            
            return {
                'status': NotificationStatus.FAILED,
                'error': f'Gmail SMTP send failed: {str(e)}',
                'sent_at': datetime.utcnow()
            }
    
    async def _send_sendgrid_email(
        self,
        recipient: Recipient,
        content: NotificationContent,
        severity: NotificationSeverity,
        notification_id: str
    ) -> Dict:
        """Send real email via SendGrid (legacy support)"""
        
        try:
            from_email = os.getenv('SENDGRID_FROM_EMAIL', 'alerts@pharmacold.com')
            
            # Create the email
            message = Mail(
                from_email=from_email,
                to_emails=recipient.email,
                subject=content.subject,
                html_content=self._format_html_email(content, severity)
            )
            
            # Add plain text version
            message.plain_text_content = content.body
            
            # Send via SendGrid
            response = self.sendgrid_client.send(message)
            
            # Log successful send
            email_payload = {
                'notification_id': notification_id,
                'timestamp': datetime.utcnow().isoformat(),
                'provider': 'sendgrid_production',
                'to': recipient.email,
                'from': from_email,
                'subject': content.subject,
                'severity': severity.value,
                'recipient_role': recipient.role.value,
                'delivery_status': 'sent',
                'sendgrid_message_id': response.headers.get('X-Message-Id', 'unknown'),
                'status_code': response.status_code
            }
            
            with open(self.log_file, 'a') as f:
                f.write(json.dumps(email_payload) + '\n')
            
            print(f"[EMAIL-PROD] Sent to {recipient.email}: {content.subject}")
            print(f"[EMAIL-PROD] SendGrid Message ID: {response.headers.get('X-Message-Id')}")
            
            return {
                'status': NotificationStatus.SENT,
                'sent_at': datetime.utcnow(),
                'delivery_metadata': {
                    'provider': 'sendgrid_production',
                    'message_id': response.headers.get('X-Message-Id'),
                    'recipient_email': recipient.email,
                    'status_code': response.status_code
                }
            }
            
        except Exception as e:
            print(f"[EMAIL-PROD] SendGrid send failed: {e}")
            
            # Log the failure
            error_payload = {
                'notification_id': notification_id,
                'timestamp': datetime.utcnow().isoformat(),
                'provider': 'sendgrid_production',
                'to': recipient.email,
                'subject': content.subject,
                'delivery_status': 'failed',
                'error': str(e)
            }
            
            with open(self.log_file, 'a') as f:
                f.write(json.dumps(error_payload) + '\n')
            
            return {
                'status': NotificationStatus.FAILED,
                'error': f'SendGrid send failed: {str(e)}',
                'sent_at': datetime.utcnow()
            }
    
    async def _send_mock_email(
        self,
        recipient: Recipient,
        content: NotificationContent,
        severity: NotificationSeverity,
        notification_id: str
    ) -> Dict:
        """Send mock email with detailed logging"""
        
        email_payload = {
            'notification_id': notification_id,
            'timestamp': datetime.utcnow().isoformat(),
            'provider': f"{self.provider}_mock",
            'to': recipient.email,
            'from': 'alerts@pharmacold.com',
            'subject': content.subject,
            'body': content.body,
            'severity': severity.value,
            'recipient_role': recipient.role.value,
            'delivery_status': 'sent_mock'
        }
        
        # Log to file
        with open(self.log_file, 'a') as f:
            f.write(json.dumps(email_payload) + '\n')
        
        print(f"[EMAIL-MOCK] Sent to {recipient.email}: {content.subject}")
        
        return {
            'status': NotificationStatus.SENT,
            'sent_at': datetime.utcnow(),
            'delivery_metadata': {
                'provider': f"{self.provider}_mock",
                'message_id': f"email_{notification_id}",
                'recipient_email': recipient.email
            }
        }
    
    def _format_html_email(self, content: NotificationContent, severity: NotificationSeverity) -> str:
        """Format email content as HTML"""
        
        severity_colors = {
            NotificationSeverity.CRITICAL: "#dc3545",  # Red
            NotificationSeverity.HIGH: "#fd7e14",      # Orange  
            NotificationSeverity.MEDIUM: "#ffc107",    # Yellow
            NotificationSeverity.LOW: "#17a2b8"        # Blue
        }
        
        color = severity_colors.get(severity, "#6c757d")
        
        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; margin: 20px;">
            <div style="border-left: 4px solid {color}; padding-left: 15px;">
                <h2 style="color: {color}; margin-top: 0;">{content.subject}</h2>
                <p style="font-size: 14px; color: #666;">
                    <strong>Priority:</strong> {severity.value.upper()}
                </p>
                <div style="margin: 15px 0;">
                    <p><strong>Summary:</strong></p>
                    <p>{content.summary}</p>
                </div>
                <div style="margin: 15px 0;">
                    <p><strong>Details:</strong></p>
                    <p>{content.body}</p>
                </div>
            </div>
            <hr style="margin: 20px 0; border: none; border-top: 1px solid #eee;">
            <p style="font-size: 12px; color: #999;">
                This is an automated notification from PharmaCold Alert System.
            </p>
        </body>
        </html>
        """
        return html_content

class SMSProvider:
    """
    SMS notification provider
    Production: Twilio, AWS SNS
    Hackathon: Mock with detailed logging
    """
    
    def __init__(self):
        self.provider = os.getenv('SMS_PROVIDER', 'mock')
        self.notification_mode = os.getenv('NOTIFICATION_MODE', 'mock')
        self.log_file = LOG_DIR / "sms_notifications.jsonl"
        
        # Initialize production client if available and enabled
        self.twilio_client = None
        if (self.provider == 'twilio' and 
            self.notification_mode == 'production' and 
            TWILIO_AVAILABLE):
            
            account_sid = os.getenv('TWILIO_ACCOUNT_SID')
            auth_token = os.getenv('TWILIO_AUTH_TOKEN')
            
            if (account_sid and auth_token and 
                account_sid != 'your_twilio_account_sid_here' and
                auth_token != 'your_twilio_auth_token_here'):
                try:
                    self.twilio_client = TwilioClient(account_sid, auth_token)
                    print(f"[SMS] Twilio client initialized for production")
                except Exception as e:
                    print(f"[SMS] Twilio initialization failed: {e}")
    
    async def send(
        self,
        recipient: Recipient,
        content: NotificationContent,
        severity: NotificationSeverity,
        notification_id: str
    ) -> Dict:
        """Send SMS notification"""
        # SMS integration is disabled for this deployment.
        return {
            'status': NotificationStatus.FAILED,
            'error': 'SMS integration is disabled in this deployment'
        }
        
        if not recipient.sms:
            return {
                'status': NotificationStatus.FAILED,
                'error': 'No SMS number provided'
            }
        
        # Determine if we should use production or mock
        use_production = (
            self.twilio_client is not None and 
            self.notification_mode == 'production'
        )
        
        if use_production:
            return await self._send_production_sms(
                recipient, content, severity, notification_id
            )
        else:
            return await self._send_mock_sms(
                recipient, content, severity, notification_id
            )
    
    async def _send_production_sms(
        self,
        recipient: Recipient,
        content: NotificationContent,
        severity: NotificationSeverity,
        notification_id: str
    ) -> Dict:
        """Send real SMS via Twilio"""
        
        try:
            from_phone = os.getenv('TWILIO_FROM_PHONE', '+1-555-PHARMA')
            
            # Create SMS-appropriate message (truncate if needed)
            sms_body = f"{severity.value.upper()}: {content.subject}\n{content.summary}"
            if len(sms_body) > 160:
                sms_body = sms_body[:157] + "..."
            
            # Send via Twilio (run in thread since Twilio is sync)
            def send_twilio_sms():
                return self.twilio_client.messages.create(
                    body=sms_body,
                    from_=from_phone,
                    to=recipient.sms
                )
            
            # Run Twilio call in thread pool
            loop = asyncio.get_event_loop()
            message = await loop.run_in_executor(None, send_twilio_sms)
            
            # Log successful send
            sms_payload = {
                'notification_id': notification_id,
                'timestamp': datetime.utcnow().isoformat(),
                'provider': 'twilio_production',
                'to': recipient.sms,
                'from': from_phone,
                'body': sms_body,
                'severity': severity.value,
                'recipient_role': recipient.role.value,
                'delivery_status': 'sent',
                'character_count': len(sms_body),
                'twilio_message_sid': message.sid,
                'twilio_status': message.status
            }
            
            with open(self.log_file, 'a') as f:
                f.write(json.dumps(sms_payload) + '\n')
            
            print(f"[SMS-PROD] Sent to {recipient.sms}: {sms_body[:50]}...")
            print(f"[SMS-PROD] Twilio SID: {message.sid}")
            
            return {
                'status': NotificationStatus.SENT,
                'sent_at': datetime.utcnow(),
                'delivery_metadata': {
                    'provider': 'twilio_production',
                    'message_id': message.sid,
                    'recipient_phone': recipient.sms,
                    'character_count': len(sms_body),
                    'twilio_status': message.status
                }
            }
            
        except Exception as e:
            print(f"[SMS-PROD] Twilio send failed: {e}")
            
            # Log the failure
            error_payload = {
                'notification_id': notification_id,
                'timestamp': datetime.utcnow().isoformat(),
                'provider': 'twilio_production',
                'to': recipient.sms,
                'body': sms_body if 'sms_body' in locals() else 'N/A',
                'delivery_status': 'failed',
                'error': str(e)
            }
            
            with open(self.log_file, 'a') as f:
                f.write(json.dumps(error_payload) + '\n')
            
            return {
                'status': NotificationStatus.FAILED,
                'error': f'Twilio send failed: {str(e)}',
                'sent_at': datetime.utcnow()
            }
    
    async def _send_mock_sms(
        self,
        recipient: Recipient,
        content: NotificationContent,
        severity: NotificationSeverity,
        notification_id: str
    ) -> Dict:
        """Send mock SMS with detailed logging"""
        
        # Create SMS-appropriate message (truncate if needed)
        sms_body = f"{content.subject}: {content.summary}"
        if len(sms_body) > 160:
            sms_body = sms_body[:157] + "..."
        
        sms_payload = {
            'notification_id': notification_id,
            'timestamp': datetime.utcnow().isoformat(),
            'provider': f"{self.provider}_mock",
            'to': recipient.sms,
            'from': '+1-555-PHARMA',
            'body': sms_body,
            'severity': severity.value,
            'recipient_role': recipient.role.value,
            'delivery_status': 'sent_mock',
            'character_count': len(sms_body)
        }
        
        # Log to file
        with open(self.log_file, 'a') as f:
            f.write(json.dumps(sms_payload) + '\n')
        
        print(f"[SMS-MOCK] Sent to {recipient.sms}: {sms_body[:50]}...")
        
        return {
            'status': NotificationStatus.SENT,
            'sent_at': datetime.utcnow(),
            'delivery_metadata': {
                'provider': f"{self.provider}_mock",
                'message_id': f"sms_{notification_id}",
                'recipient_phone': recipient.sms,
                'character_count': len(sms_body)
            }
        }

class SlackProvider:
    """
    Slack notification provider
    Production: Slack Web API
    Hackathon: Mock with detailed logging
    """
    
    def __init__(self):
        self.provider = os.getenv('SLACK_PROVIDER', 'mock')
        self.notification_mode = os.getenv('NOTIFICATION_MODE', 'mock')
        self.log_file = LOG_DIR / "slack_notifications.jsonl"
        self.default_channel = os.getenv('SLACK_DEFAULT_CHANNEL')
        self.slack_client = None

        if (self.provider == 'slack' and
            self.notification_mode == 'production' and
            SLACK_AVAILABLE):
            bot_token = os.getenv('SLACK_BOT_TOKEN')
            if bot_token and bot_token != 'xoxb-your-slack-bot-token-here':
                self.slack_client = AsyncWebClient(token=bot_token)
                print("[SLACK] Slack client initialized for production")
    
    async def send(
        self,
        recipient: Recipient,
        content: NotificationContent,
        severity: NotificationSeverity,
        notification_id: str
    ) -> Dict:
        """Send Slack notification"""
        
        if not recipient.slack_handle:
            return {
                'status': NotificationStatus.FAILED,
                'error': 'No Slack handle provided'
            }
        
        # Create professional Slack-formatted message
        slack_message = (
            f"*{content.subject}*\n"
            f"Severity: {severity.value}\n"
            f"Summary: {content.summary}\n\n"
            f"{content.body}"
        )
        
        use_production = (
            self.slack_client is not None and
            self.notification_mode == 'production'
        )

        if use_production:
            return await self._send_production_slack(
                recipient, content, severity, notification_id, slack_message
            )

        # Mock send
        slack_payload = {
            'notification_id': notification_id,
            'timestamp': datetime.utcnow().isoformat(),
            'provider': f"{self.provider}_mock",
            'channel': recipient.slack_handle,
            'text': slack_message,
            'severity': severity.value,
            'recipient_role': recipient.role.value,
            'delivery_status': 'sent_mock'
        }
        
        # Log to file
        with open(self.log_file, 'a') as f:
            f.write(json.dumps(slack_payload) + '\n')
        
        print(f"[SLACK] Sent to {recipient.slack_handle}: {content.subject}")
        
        return {
            'status': NotificationStatus.SENT,
            'sent_at': datetime.utcnow(),
            'delivery_metadata': {
                'provider': f"{self.provider}_mock",
                'message_id': f"slack_{notification_id}",
                'channel': recipient.slack_handle
            }
        }

    async def _send_production_slack(
        self,
        recipient: Recipient,
        content: NotificationContent,
        severity: NotificationSeverity,
        notification_id: str,
        slack_message: str
    ) -> Dict:
        """Send real Slack message via Slack Web API"""
        try:
            target = await self._resolve_slack_target(recipient)
            response = await self.slack_client.chat_postMessage(
                channel=target,
                text=f"{content.subject}: {content.summary}",
                mrkdwn=True,
                blocks=[
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": slack_message},
                    }
                ],
            )

            slack_payload = {
                'notification_id': notification_id,
                'timestamp': datetime.utcnow().isoformat(),
                'provider': 'slack_production',
                'channel': target,
                'text': slack_message,
                'severity': severity.value,
                'recipient_role': recipient.role.value,
                'delivery_status': 'sent',
                'slack_ok': response.get('ok', False),
                'slack_ts': response.get('ts'),
                'slack_channel': response.get('channel'),
            }

            with open(self.log_file, 'a') as f:
                f.write(json.dumps(slack_payload) + '\n')

            print(f"[SLACK-PROD] Sent to {target}: {content.subject}")
            return {
                'status': NotificationStatus.SENT,
                'sent_at': datetime.utcnow(),
                'delivery_metadata': {
                    'provider': 'slack_production',
                    'message_id': f"slack_{notification_id}",
                    'channel': target,
                    'slack_ts': response.get('ts'),
                },
            }
        except SlackApiError as e:
            error_message = e.response.get('error', str(e))
            print(f"[SLACK-PROD] Slack API error: {error_message}")
            return {
                'status': NotificationStatus.FAILED,
                'error': (
                    f"Slack API error: {error_message}. "
                    "Verify bot scopes include chat:write, channels:read, users:read.email, "
                    "then reinstall the app."
                ),
                'sent_at': datetime.utcnow()
            }
        except Exception as e:
            print(f"[SLACK-PROD] Slack send failed: {e}")
            return {
                'status': NotificationStatus.FAILED,
                'error': f'Slack send failed: {str(e)}',
                'sent_at': datetime.utcnow()
            }

    async def _resolve_slack_target(self, recipient: Recipient) -> str:
        """Resolve Slack target from recipient data."""
        handle = (recipient.slack_handle or "").strip()

        # If explicit channel/user/conversation ID, use directly.
        if handle.startswith(("C", "G", "D", "U")):
            return handle

        # Channel name format like #alerts.
        if handle.startswith("#"):
            return handle

        # For @mentions, attempt to resolve using recipient email.
        if handle.startswith("@"):
            if recipient.email:
                lookup = await self.slack_client.users_lookupByEmail(email=recipient.email)
                user_id = lookup.get("user", {}).get("id")
                if user_id:
                    return user_id
            raise ValueError(
                f"Unable to resolve Slack user for handle '{handle}'. "
                "Use slack user ID (U...) or set recipient email with users:read.email scope."
            )

        if self.default_channel:
            return self.default_channel

        raise ValueError(
            "No valid Slack target. Set recipient.slack_handle to #channel, U.../C... ID, "
            "or configure SLACK_DEFAULT_CHANNEL."
        )

class NotificationChannelManager:
    """Manages all notification channel providers"""
    
    def __init__(self):
        self.email = EmailProvider()
        # SMS provider disabled for current deployment.
        # self.sms = SMSProvider()
        self.sms = None
        self.slack = SlackProvider()
    
    async def send_notification(
        self,
        channel: NotificationChannel,
        recipient: Recipient,
        content: NotificationContent,
        severity: NotificationSeverity,
        notification_id: str,
        metadata: Dict = None
    ) -> Dict:
        """Send notification through specified channel"""
        
        try:
            if channel == NotificationChannel.EMAIL:
                return await self.email.send(recipient, content, severity, notification_id)
            elif channel == NotificationChannel.SMS:
                return {
                    'status': NotificationStatus.FAILED,
                    'error': 'SMS integration is disabled in this deployment'
                }
            elif channel == NotificationChannel.SLACK:
                return await self.slack.send(recipient, content, severity, notification_id)
            elif channel == NotificationChannel.DASHBOARD:
                return await self._send_dashboard_update(recipient, content, severity, notification_id)
            elif channel == NotificationChannel.WEBHOOK:
                return await self._send_webhook(recipient, content, severity, notification_id, metadata)
            else:
                return {
                    'status': NotificationStatus.FAILED,
                    'error': f'Unsupported channel: {channel.value}'
                }
        
        except Exception as e:
            return {
                'status': NotificationStatus.FAILED,
                'error': str(e),
                'sent_at': datetime.utcnow()
            }
    
    async def _send_dashboard_update(
        self,
        recipient: Recipient,
        content: NotificationContent,
        severity: NotificationSeverity,
        notification_id: str
    ) -> Dict:
        """Send dashboard update (mock implementation)"""
        
        dashboard_payload = {
            'notification_id': notification_id,
            'timestamp': datetime.utcnow().isoformat(),
            'recipient_id': recipient.recipient_id,
            'severity': severity.value,
            'content': {
                'subject': content.subject,
                'summary': content.summary
            },
            'delivery_status': 'posted'
        }
        
        # Log to dashboard file
        dashboard_log = LOG_DIR / "dashboard_notifications.jsonl"
        with open(dashboard_log, 'a') as f:
            f.write(json.dumps(dashboard_payload) + '\n')
        
        print(f"[DASHBOARD] Posted for {recipient.recipient_id}: {content.subject}")
        
        return {
            'status': NotificationStatus.SENT,
            'sent_at': datetime.utcnow(),
            'delivery_metadata': {
                'provider': 'dashboard',
                'message_id': f"dash_{notification_id}",
                'recipient_id': recipient.recipient_id
            }
        }
    
    async def _send_webhook(
        self,
        recipient: Recipient,
        content: NotificationContent,
        severity: NotificationSeverity,
        notification_id: str,
        metadata: Dict = None
    ) -> Dict:
        """Send webhook notification (mock implementation)"""
        
        webhook_payload = {
            'notification_id': notification_id,
            'timestamp': datetime.utcnow().isoformat(),
            'recipient': recipient.dict(),
            'content': content.dict(),
            'severity': severity.value,
            'metadata': metadata or {},
            'delivery_status': 'sent'
        }
        
        # Log to webhook file
        webhook_log = LOG_DIR / "webhook_notifications.jsonl"
        with open(webhook_log, 'a') as f:
            f.write(json.dumps(webhook_payload) + '\n')
        
        print(f"[WEBHOOK] Sent for {recipient.recipient_id}: {content.subject}")
        
        return {
            'status': NotificationStatus.SENT,
            'sent_at': datetime.utcnow(),
            'delivery_metadata': {
                'provider': 'webhook',
                'message_id': f"webhook_{notification_id}",
                'recipient_id': recipient.recipient_id
            }
        }