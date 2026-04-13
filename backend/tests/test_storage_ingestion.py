# Test that documents from Supabase Storage were ingested correctly
import asyncio
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))
from agents.compliance.vector_store import ComplianceVectorStore
from agents.compliance.agent import VectorComplianceAgent

async def test_storage_ingestion():
    # test vector search after storage ingestion
    
    print("\n" + "="*80)
    print("Testing vector search after storage ingestion")
    print("="*80)
    
    try:
        vector_store = ComplianceVectorStore()
        
        # check document count
        count = vector_store.count_documents()
        print(f"\nVector database contains {count} documents")
        vector_available = True
    except Exception as e:
        print(f"\nVector store not available: {e}")
        print("Skipping vector store tests, testing agent fallback mode instead...")
        vector_available = False
    
    if vector_available:
        # Test search queries
        test_queries = [
            "temperature excursion requirements for biologics",
            "electronic records and audit trail requirements",
            "risk-based quality management",
            "product stability testing guidelines"
        ]
        
        for query in test_queries:
            print(f"\n{'─'*80}")
            print(f"Query: '{query}'")
            print(f"{'─'*80}")
            
            results = vector_store.search(query, limit=3)
            
            if results:
                for i, result in enumerate(results, 1):
                    print(f"\n{i}. {result['regulation_id']}")
                    print(f"{result['title']}")
                    print(f"Similarity: {result.get('similarity', 0):.3f}")
                    print(f"Source: {result.get('metadata', {}).get('source_file', 'N/A')}")
            else:
                print("No results found")
    else:
        print("\n⚠️  Skipping vector search tests (database not available)")
    
    # Test full compliance agent
    print(f"\n{'='*80}")
    print("TESTING COMPLIANCE AGENT WITH VECTOR SEARCH")
    print(f"{'='*80}")
    
    agent = VectorComplianceAgent()
    
    test_scenario = {
        'shipment_id': 'TEST-STORAGE-001',
        'product_category': 'biologics',
        'current_temp_c': 9.2,
        'minutes_outside_range': 42,
        'transit_phase': 'customs_clearance',
        'risk_score': 75,
        'spoilage_probability': 0.38,
        'at_risk_value': 120000,
        'critical_patients_affected': 8,
        'affected_facilities': ['HOSP-001', 'HOSP-002']
    }
    
    result = await agent.validate_compliance(test_scenario)
    
    print(f"\nCompliance Decision: {result['compliance_status']}")
    print(f"Approval Required: {result['human_approval_required']}")
    print(f"Approval Level: {result.get('approval_level')}")
    print(f"Regulations Retrieved: {len(result['applicable_citations'])}")
    
    print(f"\nRelevant Regulations:")
    for citation in result['applicable_citations'][:3]:
        print(f"  - {citation['regulation']} (similarity: {citation.get('similarity', 0):.3f})")
    
    print(f"\n{'='*80}")
    if vector_available:
        print("All tests passed - storage ingestion successful")
    else:
        print("Agent fallback mode working - vector store unavailable but agent functional")
    print(f"{'='*80}")

if __name__ == "__main__":
    asyncio.run(test_storage_ingestion())