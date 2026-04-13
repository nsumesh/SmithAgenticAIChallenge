# Script to ingest compliance documents from Supabase Storage into vector store
import os
import sys
import tempfile
from pathlib import Path
from io import BytesIO
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add backend to path for proper imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from supabase import create_client, Client


# Try relative imports first (when imported as module), then absolute imports (when run directly)
try:
    from .document_parser import ComplianceDocumentParser
    from .vector_store import ComplianceVectorStore
except ImportError:
    # Fallback for direct execution
    sys.path.insert(0, str(Path(__file__).parent))
    from document_parser import ComplianceDocumentParser
    from vector_store import ComplianceVectorStore

# document metadata (maps to files in Supabase Storage)
DOCUMENTS = [
    {
        'storage_path': 'who_trs_961_annex_9.pdf',  # path in Supabase Storage bucket
        'regulation_id': 'WHO-TRS961-ANNEX9',
        'regulation_name': 'WHO TRS 961 Annex 9 - Model guidance for storage and transport',
        'authority': 'World Health Organization',
        'url': 'https://www.who.int/publications/i/item/9789241547239',
        'product_categories': ['all'],
        'applies_to': ['storage', 'transport']
    },
    {
        'storage_path': 'eu_gdp_guidelines.pdf',
        'regulation_id': 'EU-GDP',
        'regulation_name': 'EU Guidelines on Good Distribution Practice',
        'authority': 'European Commission',
        'url': 'https://ec.europa.eu/health/documents/eudralex/vol-9_en',
        'product_categories': ['all'],
        'applies_to': ['distribution', 'storage', 'transport']
    },
    {
        'storage_path': 'eu_gdp_human_use.pdf',
        'regulation_id': 'EU-GDP-HUMAN',
        'regulation_name': 'EU GDP Guidelines for Medicinal Products for Human Use',
        'authority': 'European Commission',
        'url': 'https://ec.europa.eu/health/documents/eudralex/vol-9_en',
        'product_categories': ['all'],
        'applies_to': ['distribution', 'human_use']
    },
    {
        'storage_path': 'iata_vaccine_logistics.pdf',
        'regulation_id': 'IATA-VACCINE',
        'regulation_name': 'IATA Guidelines for Vaccine Logistics',
        'authority': 'International Air Transport Association',
        'url': 'https://www.iata.org/en/programs/cargo/pharma/',
        'product_categories': ['biologics', 'vaccines'],
        'applies_to': ['transport', 'air_freight']
    },
    {
        'storage_path': 'fda_21_cfr_part_11.pdf',
        'regulation_id': 'FDA-21CFR11',
        'regulation_name': 'FDA 21 CFR Part 11 - Electronic Records',
        'authority': 'US FDA',
        'url': 'https://www.fda.gov/regulatory-information',
        'product_categories': ['all'],
        'applies_to': ['electronic_records', 'audit_trail']
    },
    {
        'storage_path': 'ich_q9_quality_risk_management.pdf',
        'regulation_id': 'ICH-Q9',
        'regulation_name': 'ICH Q9 Quality Risk Management',
        'authority': 'ICH (FDA, EMA, MHLW)',
        'url': 'https://database.ich.org/sites/default/files/Q9%20Guideline.pdf',
        'product_categories': ['all'],
        'applies_to': ['risk_management', 'quality_system']
    },
    # {
    #     'storage_path': 'ich_q1a_stability_testing.pdf',
    #     'regulation_id': 'ICH-Q1A',
    #     'regulation_name': 'ICH Q1A(R2) Stability Testing',
    #     'authority': 'ICH (FDA, EMA, MHLW)',
    #     'url': 'https://database.ich.org/sites/default/files/Q1A-R2-Guideline.pdf',
    #     'product_categories': ['all'],
    #     'applies_to': ['stability', 'product_disposition']
    # },
    # {
    #     'storage_path': 'ich_q10_quality_system.pdf',
    #     'regulation_id': 'ICH-Q10',
    #     'regulation_name': 'ICH Q10 Pharmaceutical Quality System',
    #     'authority': 'ICH (FDA, EMA, MHLW)',
    #     'url': 'https://database.ich.org/sites/default/files/Q10%20Guideline.pdf',
    #     'product_categories': ['all'],
    #     'applies_to': ['quality_system', 'capa']
    # },
    {
        'storage_path': 'pics_gdp_guide.pdf',
        'regulation_id': 'PICS-GDP',
        'regulation_name': 'PIC/S GDP Guide for Medicinal Products',
        'authority': 'Pharmaceutical Inspection Co-operation Scheme',
        'url': 'https://www.picscheme.org/en/publications',
        'product_categories': ['all'],
        'applies_to': ['distribution', 'quality_management']
    },
]

class SupabaseStorageClient:

    # client for fetching files from Supabase Storage
    
    def __init__(self, bucket_name: str = 'compliance_docs'):
        supabase_url = os.getenv('SUPABASE_URL')
        supabase_key = os.getenv('SUPABASE_KEY')
        
        if not supabase_url or not supabase_key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in .env")
        
        self.client: Client = create_client(supabase_url, supabase_key)
        self.bucket_name = bucket_name
        
        print(f"[STORAGE] Connected to Supabase Storage")
        print(f"[STORAGE] Bucket: {bucket_name}")
        print(f"[DEBUG] Supabase URL: {supabase_url}")
        print(f"[DEBUG] API Key: ***{supabase_key[-10:] if len(supabase_key) > 10 else '***'}")
        
        # Test if we can access storage at all
        try:
            buckets = self.client.storage.list_buckets()
            print(f"[DEBUG] Available buckets: {[b.name for b in buckets]}")
        except Exception as e:
            print(f"[DEBUG] Could not list buckets: {e}")
    
    def list_files(self) -> list:
        # list all files in the bucket
        try:
            print(f"[DEBUG] Attempting to list files from bucket: {self.bucket_name}")
            files = self.client.storage.from_(self.bucket_name).list()
            print(f"[DEBUG] Raw response from list(): {files}")
            print(f"[DEBUG] Response type: {type(files)}")
            
            if files:
                print(f"[DEBUG] Found {len(files)} items")
                for i, file in enumerate(files[:3]):  # Show first 3 files for debugging
                    print(f"[DEBUG] File {i}: {file}")
            
            return files if files else []
        except Exception as e:
            print(f"[ERROR] Failed to list files: {e}")
            print(f"[ERROR] Error type: {type(e)}")
            import traceback
            traceback.print_exc()
            return []
    
    def download_file(self, file_path: str) -> bytes:
        # download file from Supabase Storage
        try:
            print(f"[STORAGE] Downloading: {file_path}")
            
            # Download file
            response = self.client.storage.from_(self.bucket_name).download(file_path)
            
            if response:
                print(f"Downloaded {len(response)} bytes")
                return response
            else:
                print(f"[ERROR] Empty response for {file_path}")
                return None
                
        except Exception as e:
            print(f"[ERROR] Failed to download {file_path}: {e}")
            return None
    
    def get_public_url(self, file_path: str) -> str:
        # get public URL for a file (if bucket is public)
        try:
            url = self.client.storage.from_(self.bucket_name).get_public_url(file_path)
            return url
        except Exception as e:
            print(f"[ERROR] Failed to get public URL: {e}")
            return None


def ingest_documents():
    # ingest all compliance documents from Supabase Storage
    print("="*80)
    print("Ingesting compliance documents from Supabase Storage")
    print("="*80)
    
    # Initialize clients
    storage_client = SupabaseStorageClient(bucket_name='compliance_docs')
    parser = ComplianceDocumentParser(chunk_size=500, chunk_overlap=50)
    vector_store = ComplianceVectorStore()
    
    # List available files in storage
    print("\n[INFO] Checking Supabase Storage bucket...")
    available_files = storage_client.list_files()
    
    if not available_files:
        print("No files found in Supabase Storage bucket 'compliance_docs'")
        return
    
    print(f"[INFO] Found {len(available_files)} files in storage:")
    for file in available_files:
        print(f"  - {file['name']} ({file.get('metadata', {}).get('size', 0) / 1024:.1f} KB)")
    
    # Check current document count in vector store
    existing_count = vector_store.count_documents()
    print(f"\n[INFO] Existing documents in vector database: {existing_count}")
    
    if existing_count > 0:
        response = input("\nVector database already contains documents. Delete and re-ingest? (yes/no): ")
        if response.lower() == 'yes':
            vector_store.delete_all()
            print("[INFO] Deleted existing documents")
        else:
            print("[INFO] Keeping existing documents. Exiting.")
            return
    
    # Process each document
    all_chunks = []
    processed_count = 0
    skipped_count = 0
    
    for doc_meta in DOCUMENTS:
        storage_path = doc_meta['storage_path']
        
        print(f"\n{'='*80}")
        print(f"Processing: {doc_meta['regulation_name']}")
        print(f"{'='*80}")
        print(f"Storage path: {storage_path}")
        
        # Download file from Supabase Storage
        file_bytes = storage_client.download_file(storage_path)
        
        if not file_bytes:
            print(f"[WARNING] Failed to download: {storage_path}")
            print(f"[INFO] Skipping {doc_meta['regulation_name']}")
            skipped_count += 1
            continue
        
        # Save to temporary file for parsing
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
            tmp_file.write(file_bytes)
            tmp_path = tmp_file.name
        
        try:
            # Add storage path to metadata
            doc_meta['source_file'] = storage_path
            doc_meta['source_type'] = 'supabase_storage'
            doc_meta['bucket'] = 'compliance_docs'
            
            # Parse PDF
            chunks = parser.parse_pdf(tmp_path, metadata=doc_meta)
            all_chunks.extend(chunks)
            
            print(f" Extracted {len(chunks)} chunks")
            processed_count += 1
            
        except Exception as e:
            print(f"[ERROR] Failed to parse PDF: {e}")
            skipped_count += 1
        
        finally:
            # Clean up temporary file
            try:
                os.unlink(tmp_path)
            except:
                pass
    
    # Add all chunks to vector store
    if all_chunks:
        print(f"\n{'='*80}")
        print(f"UPLOADING TO SUPABASE VECTOR DATABASE")
        print(f"{'='*80}")
        
        inserted = vector_store.add_documents(all_chunks)
        
        print(f"\n{'='*80}")
        print(f"INGESTION COMPLETE")
        print(f"{'='*80}")
        print(f" Total documents processed: {processed_count}")
        print(f" Total documents skipped: {skipped_count}")
        print(f" Total chunks extracted: {len(all_chunks)}")
        print(f" Successfully inserted: {inserted}")
        print(f" Vector database now contains: {vector_store.count_documents()} documents")
        
        # Show sample search
        print(f"\n{'='*80}")
        print(f"SAMPLE SEARCH TEST")
        print(f"{'='*80}")
        
        test_query = "temperature excursion requirements for biologics"
        print(f"Query: '{test_query}'")
        
        results = vector_store.search(test_query, limit=3)
        
        if results:
            print(f"\nTop {len(results)} results:")
            for i, result in enumerate(results, 1):
                print(f"\n{i}. {result['regulation_id']} - {result['title']}")
                print(f"   Authority: {result['authority']}")
                print(f"   Similarity: {result.get('similarity', 0):.3f}")
                print(f"   Content preview: {result['content'][:150]}...")
        else:
            print("[WARNING] No results found. Check embeddings.")
    else:
        print("No documents were successfully processed")


def list_storage_files():
    # helper function to list files in Supabase Storage
    print("="*80)
    print("FILES IN SUPABASE STORAGE BUCKET 'compliance_docs'")
    print("="*80)
    
    storage_client = SupabaseStorageClient(bucket_name='compliance_docs')
    files = storage_client.list_files()
    
    if not files:
        print("\nNo files found in bucket")
        return
    
    print(f"\nFound {len(files)} files:\n")
    
    for file in files:
        name = file['name']
        size = file.get('metadata', {}).get('size', 0)
        created = file.get('created_at', 'Unknown')
        
        print(f"{name}")
        print(f"Size: {size / 1024:.1f} KB")
        print(f"Created: {created}")
        print()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Ingest compliance documents from Supabase Storage')
    parser.add_argument('--list', action='store_true', help='List files in Supabase Storage')
    
    args = parser.parse_args()
    
    if args.list:
        list_storage_files()
    else:
        ingest_documents()