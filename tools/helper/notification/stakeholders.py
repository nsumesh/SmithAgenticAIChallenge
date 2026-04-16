"""
Stakeholder contact registry for pharmaceutical supply chain
In production: Load from database or external CRM
"""
from typing import Dict, List, Optional

# Handle both relative and absolute imports
try:
    from .models import Recipient, RecipientRole
except ImportError:
    from tools.helper.notification.models import Recipient, RecipientRole

class StakeholderRegistry:
    """Manages stakeholder contact information"""
    
    def __init__(self):
        # In production: Load from database
        # For hackathon: Hardcoded registry
        self.stakeholders = self._initialize_registry()
    
    def _initialize_registry(self) -> Dict:
        """Initialize stakeholder contact database"""
        return {
            'internal': {
                'director': Recipient(
                    recipient_id='DIR-001',
                    role=RecipientRole.DIRECTOR,
                    name='Dr. Robert Chen',
                    email='robert.chen@pharmacold.com',
                    sms='+1-555-0001',
                    slack_handle='@robert.chen',
                    priority='URGENT',
                    on_call=True
                ),
                'qa_managers': [
                    Recipient(
                        recipient_id='QA-001',
                        role=RecipientRole.QA_MANAGER,
                        name='Sarah Martinez',
                        email='sarah.martinez@pharmacold.com',
                        sms='+1-555-0100',
                        slack_handle='@sarah.martinez',
                        priority='HIGH',
                        on_call=True
                    ),
                    Recipient(
                        recipient_id='QA-002',
                        role=RecipientRole.QA_MANAGER,
                        name='David Kim',
                        email='david.kim@pharmacold.com',
                        sms='+1-555-0101',
                        slack_handle='@david.kim',
                        priority='HIGH',
                        on_call=False
                    )
                ],
                'logistics_ops': [
                    Recipient(
                        recipient_id='OPS-001',
                        role=RecipientRole.LOGISTICS_OPS,
                        name='Maria Rodriguez',
                        email='maria.rodriguez@pharmacold.com',
                        sms='+1-555-0200',
                        slack_handle='@maria.rodriguez',
                        priority='HIGH',
                        on_call=True
                    ),
                    Recipient(
                        recipient_id='OPS-002',
                        role=RecipientRole.LOGISTICS_OPS,
                        name='James Wilson',
                        email='james.wilson@pharmacold.com',
                        sms='+1-555-0201',
                        slack_handle='@james.wilson',
                        priority='NORMAL',
                        on_call=False
                    )
                ]
            },
            'external': {
                'hospital_admins': {
                    'General Hospital': Recipient(
                        recipient_id='HOSP-001',
                        role=RecipientRole.HOSPITAL_ADMIN,
                        name='Dr. Lisa Thompson',
                        email='lisa.thompson@generalhospital.org',
                        sms='+1-555-1001',
                        facility_id='HOSP-GEN-001',
                        priority='HIGH'
                    ),
                    'City Medical Center': Recipient(
                        recipient_id='HOSP-002',
                        role=RecipientRole.HOSPITAL_ADMIN,
                        name='Michael Chang',
                        email='michael.chang@citymedical.org',
                        sms='+1-555-1002',
                        facility_id='HOSP-CITY-001',
                        priority='HIGH'
                    ),
                    'Regional Health System': Recipient(
                        recipient_id='HOSP-003',
                        role=RecipientRole.HOSPITAL_ADMIN,
                        name='Dr. Amanda Foster',
                        email='amanda.foster@regionalhealthsystem.org',
                        sms='+1-555-1003',
                        facility_id='HOSP-REG-001',
                        priority='NORMAL'
                    )
                },
                'pharmacy_directors': {
                    'Central Pharmacy': Recipient(
                        recipient_id='PHARM-001',
                        role=RecipientRole.PHARMACY_DIRECTOR,
                        name='Dr. Kevin Park',
                        email='kevin.park@centralpharmacy.com',
                        sms='+1-555-2001',
                        facility_id='PHARM-CENT-001',
                        priority='HIGH'
                    ),
                    'Metro Pharmacy Network': Recipient(
                        recipient_id='PHARM-002',
                        role=RecipientRole.PHARMACY_DIRECTOR,
                        name='Jennifer Adams',
                        email='jennifer.adams@metropharmacy.com',
                        sms='+1-555-2002',
                        facility_id='PHARM-METRO-001',
                        priority='NORMAL'
                    )
                }
            }
        }
    
    def get_director(self) -> Recipient:
        """Get the company director"""
        return self.stakeholders['internal']['director']
    
    def get_qa_manager_on_call(self) -> Optional[Recipient]:
        """Get the QA manager currently on call"""
        qa_managers = self.stakeholders['internal']['qa_managers']
        for qa in qa_managers:
            if qa.on_call:
                return qa
        # Fallback to first QA manager if none on call
        return qa_managers[0] if qa_managers else None
    
    def get_logistics_ops(self) -> Recipient:
        """Get logistics operations contact"""
        ops_team = self.stakeholders['internal']['logistics_ops']
        # Return on-call ops person or first available
        for ops in ops_team:
            if ops.on_call:
                return ops
        return ops_team[0] if ops_team else None
    
    def get_hospital_contact(self, facility_name: str) -> Optional[Recipient]:
        """Get hospital admin contact for specific facility"""
        hospital_admins = self.stakeholders['external']['hospital_admins']
        
        # Try exact match first
        if facility_name in hospital_admins:
            return hospital_admins[facility_name]
        
        # Try partial match
        for name, contact in hospital_admins.items():
            if facility_name.lower() in name.lower() or name.lower() in facility_name.lower():
                return contact
        
        return None
    
    def get_all_affected_hospital_contacts(self, facility_names: List[str]) -> List[Recipient]:
        """Get all hospital contacts for affected facilities"""
        contacts = []
        for facility in facility_names:
            contact = self.get_hospital_contact(facility)
            if contact:
                contacts.append(contact)
        return contacts
    
    def get_pharmacy_contact(self, facility_name: str) -> Optional[Recipient]:
        """Get pharmacy director contact for specific facility"""
        pharmacy_directors = self.stakeholders['external']['pharmacy_directors']
        
        # Try exact match first
        if facility_name in pharmacy_directors:
            return pharmacy_directors[facility_name]
        
        # Try partial match
        for name, contact in pharmacy_directors.items():
            if facility_name.lower() in name.lower() or name.lower() in facility_name.lower():
                return contact
        
        return None
    
    def get_all_affected_pharmacy_contacts(self, facility_names: List[str]) -> List[Recipient]:
        """Get all pharmacy contacts for affected facilities"""
        contacts = []
        for facility in facility_names:
            contact = self.get_pharmacy_contact(facility)
            if contact:
                contacts.append(contact)
        return contacts
    
    def get_regulatory_contacts(self) -> List[Recipient]:
        """Get regulatory authority contacts (if any)"""
        # In production: Return FDA, EMA, etc. contacts for serious violations
        return []
    
    def search_by_role(self, role: RecipientRole) -> List[Recipient]:
        """Search all contacts by role"""
        contacts = []
        
        # Search internal contacts
        for category, data in self.stakeholders['internal'].items():
            if isinstance(data, list):
                for contact in data:
                    if contact.role == role:
                        contacts.append(contact)
            elif isinstance(data, Recipient) and data.role == role:
                contacts.append(data)
        
        # Search external contacts
        for category, facilities in self.stakeholders['external'].items():
            for facility_name, contact in facilities.items():
                if contact.role == role:
                    contacts.append(contact)
        
        return contacts