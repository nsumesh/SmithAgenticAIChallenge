"""
Notification configuration management utility
Helps validate and manage production API credentials
"""
import os
from typing import Dict, List, Optional
from pathlib import Path

def check_notification_config() -> Dict[str, Dict]:
    """Check notification service configuration and return status"""
    
    config_status = {}
    
    # Check general configuration
    notification_mode = os.getenv('NOTIFICATION_MODE', 'mock')
    config_status['general'] = {
        'notification_mode': notification_mode,
        'production_enabled': notification_mode == 'production'
    }
    
    # Check Email configuration (Gmail SMTP or SendGrid)
    email_provider = os.getenv('EMAIL_PROVIDER', 'mock')
    
    email_config = {
        'provider': email_provider,
        'ready_for_production': False
    }
    
    if email_provider == 'gmail_smtp':
        gmail_email = os.getenv('GMAIL_EMAIL')
        gmail_password = os.getenv('GMAIL_APP_PASSWORD')
        
        email_config.update({
            'gmail_email_set': bool(gmail_email and gmail_email != 'your-gmail@gmail.com'),
            'gmail_password_set': bool(gmail_password and gmail_password != 'your_16_character_app_password_here'),
            'gmail_email': gmail_email if gmail_email != 'your-gmail@gmail.com' else 'Not set',
            'from_name': os.getenv('GMAIL_FROM_NAME', 'PharmaCold Alert System')
        })
        
        email_config['ready_for_production'] = (
            email_config['gmail_email_set'] and
            email_config['gmail_password_set'] and
            notification_mode == 'production'
        )
    
    elif email_provider == 'sendgrid':
        sendgrid_api_key = os.getenv('SENDGRID_API_KEY')
        
        email_config.update({
            'api_key_set': bool(sendgrid_api_key and sendgrid_api_key != 'your_sendgrid_api_key_here'),
            'from_email': os.getenv('SENDGRID_FROM_EMAIL', 'alerts@pharmacold.com')
        })
        
        email_config['ready_for_production'] = (
            email_config['api_key_set'] and
            notification_mode == 'production'
        )
    
    config_status['email'] = email_config
    
    # Check Twilio configuration  
    twilio_config = {
        'provider': os.getenv('SMS_PROVIDER', 'mock'),
        'account_sid_set': bool(os.getenv('TWILIO_ACCOUNT_SID') and 
                               os.getenv('TWILIO_ACCOUNT_SID') != 'your_twilio_account_sid_here'),
        'auth_token_set': bool(os.getenv('TWILIO_AUTH_TOKEN') and 
                              os.getenv('TWILIO_AUTH_TOKEN') != 'your_twilio_auth_token_here'),
        'from_phone': os.getenv('TWILIO_FROM_PHONE', '+1-555-PHARMA'),
        'ready_for_production': False
    }
    
    twilio_config['ready_for_production'] = (
        twilio_config['provider'] == 'twilio' and
        twilio_config['account_sid_set'] and
        twilio_config['auth_token_set'] and
        notification_mode == 'production'
    )
    
    config_status['twilio'] = twilio_config
    
    # Check Slack configuration
    slack_config = {
        'provider': os.getenv('SLACK_PROVIDER', 'mock'),
        'bot_token_set': bool(os.getenv('SLACK_BOT_TOKEN') and 
                             os.getenv('SLACK_BOT_TOKEN') != 'xoxb-your-slack-bot-token-here'),
        'ready_for_production': False
    }
    
    slack_config['ready_for_production'] = (
        slack_config['provider'] == 'slack' and
        slack_config['bot_token_set'] and
        notification_mode == 'production'
    )
    
    config_status['slack'] = slack_config
    
    return config_status

def print_notification_config():
    """Print a formatted status of notification configuration"""
    
    config = check_notification_config()
    
    print("=" * 60)
    print("  NOTIFICATION SYSTEM CONFIGURATION")
    print("=" * 60)
    
    # General status
    general = config['general']
    mode = general['notification_mode']
    prod_enabled = general['production_enabled']
    
    print(f"\n📋 General Configuration:")
    print(f"  Mode: {mode.upper()}")
    print(f"  Production Enabled: {'✅' if prod_enabled else '❌'}")
    
    # Service status
    email_provider_name = config['email']['provider'].replace('_', ' ').title()
    services = [
        (f'📧 Email ({email_provider_name})', config['email']),
        ('📱 SMS (Twilio)', config['twilio']), 
        ('💬 Slack', config['slack'])
    ]
    
    print(f"\n📡 Service Status:")
    for service_name, service_config in services:
        provider = service_config['provider']
        ready = service_config['ready_for_production']
        
        print(f"  {service_name}:")
        print(f"    Provider: {provider}")
        print(f"    Production Ready: {'✅' if ready else '❌'}")
        
        # Show specific missing items
        if not ready and mode == 'production':
            missing = []
            if 'api_key_set' in service_config and not service_config['api_key_set']:
                missing.append("API Key")
            if 'gmail_email_set' in service_config and not service_config['gmail_email_set']:
                missing.append("Gmail Email")
            if 'gmail_password_set' in service_config and not service_config['gmail_password_set']:
                missing.append("Gmail App Password")
            if 'account_sid_set' in service_config and not service_config['account_sid_set']:
                missing.append("Account SID")
            if 'auth_token_set' in service_config and not service_config['auth_token_set']:
                missing.append("Auth Token")
            if 'bot_token_set' in service_config and not service_config['bot_token_set']:
                missing.append("Bot Token")
            
            if missing:
                print(f"    Missing: {', '.join(missing)}")
    
    print(f"\n💡 Tips:")
    if not prod_enabled:
        print(f"  - Set NOTIFICATION_MODE=production to enable real API calls")
    
    any_ready = any(service['ready_for_production'] for service in 
                    [config['email'], config['twilio'], config['slack']])
    
    if prod_enabled and not any_ready:
        print(f"  - Configure at least one service with real API credentials")
        print(f"  - Update .env file with your API keys")
    
    if any_ready:
        print(f"  - Production services are configured and ready!")
    
    print("=" * 60)

def validate_sendgrid_key(api_key: str) -> bool:
    """Validate SendGrid API key format (basic check)"""
    return (api_key and 
            api_key.startswith('SG.') and 
            len(api_key) > 20)

def validate_twilio_credentials(account_sid: str, auth_token: str) -> bool:
    """Validate Twilio credentials format (basic check)"""
    return (account_sid and auth_token and
            account_sid.startswith('AC') and
            len(account_sid) == 34 and
            len(auth_token) == 32)

def validate_slack_token(bot_token: str) -> bool:
    """Validate Slack bot token format (basic check)"""
    return (bot_token and 
            bot_token.startswith('xoxb-') and 
            len(bot_token) > 20)

def get_setup_instructions() -> str:
    """Get setup instructions for production credentials"""
    
    instructions = """
NOTIFICATION SYSTEM SETUP INSTRUCTIONS
=====================================

To enable production notifications, follow these steps:

1. UPDATE ENVIRONMENT VARIABLES
   Edit your .env file with:
   
   NOTIFICATION_MODE=production
   
2. GMAIL SMTP EMAIL SETUP (FREE!)
   - Use your existing Gmail account
   - Enable 2-Factor Authentication in Google Account settings
   - Generate App Password: Google Account > Security > App passwords
   - Add to .env:
     EMAIL_PROVIDER=gmail_smtp
     GMAIL_EMAIL=your-actual-email@gmail.com
     GMAIL_APP_PASSWORD=your_16_character_app_password
     GMAIL_FROM_NAME=Your Company Alert System
   
   Alternative - SENDGRID EMAIL SETUP
   - Sign up at https://sendgrid.com (has free tier)
   - Create an API key in Settings > API Keys
   - Add to .env:
     EMAIL_PROVIDER=sendgrid
     SENDGRID_API_KEY=SG.your_actual_api_key_here
     SENDGRID_FROM_EMAIL=alerts@yourdomain.com
   
3. TWILIO SMS SETUP
   - Sign up at https://twilio.com
   - Get Account SID and Auth Token from Console
   - Purchase a phone number
   - Add to .env:
     TWILIO_ACCOUNT_SID=your_account_sid_here
     TWILIO_AUTH_TOKEN=your_auth_token_here
     TWILIO_FROM_PHONE=+1234567890
     
4. SLACK SETUP (Required for workspace notifications)
   - Create a Slack app at https://api.slack.com/apps
   - Add Bot Token Scopes: chat:write, channels:read, users:read.email
   - Install app to workspace
   - Reinstall app after any scope changes
   - Add to .env:
     SLACK_BOT_TOKEN=xoxb-your-bot-token-here

5. TEST CONFIGURATION
   Run: python -c "from tools.helper.notification.config import print_notification_config; print_notification_config()"

6. VERIFY PRODUCTION MODE
   Run a notification test to confirm real API calls are working.

SECURITY NOTES:
- Never commit real API keys to git
- Use environment variables or secure key management
- Monitor API usage and costs
- Set up proper error alerts
"""
    return instructions

if __name__ == "__main__":
    print_notification_config()
    print("\n")
    print(get_setup_instructions())