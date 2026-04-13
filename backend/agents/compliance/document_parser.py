# Parse compliance documents (PDFs) into chunks for vectorization
import re
from typing import List, Dict
from pathlib import Path
from pypdf import PdfReader

class ComplianceDocumentParser:
    # parse regulatory PDFs into structured chunks
    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
    
    def parse_pdf(self, pdf_path: str, metadata: Dict) -> List[Dict]:
        # parse PDF into chunks with metadata
        print(f"Parsing PDF {pdf_path}...")
        
        # Read PDF and extract text
        reader = PdfReader(pdf_path)
        full_text = ""
        
        for page_num, page in enumerate(reader.pages):
            text = page.extract_text()
            full_text += f"\n[Page {page_num + 1}]\n{text}"
        
        # Clean text
        full_text = self._clean_text(full_text)
        
        # Split into sections (try to detect section headers)
        sections = self._split_into_sections(full_text, metadata)
        
        # Chunk each section
        chunks = []
        for section in sections:
            section_chunks = self._chunk_text(
                text=section['content'],
                section_metadata=section
            )
            chunks.extend(section_chunks)
        
        print(f"[PARSER] Created {len(chunks)} chunks from {len(reader.pages)} pages")
        return chunks
    
    def _clean_text(self, text: str) -> str:
        # clean extracted text - remove excessive whitespaces
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)
        
        # Remove page numbers at start of lines
        text = re.sub(r'^\d+\s*$', '', text, flags=re.MULTILINE)
        
        return text.strip()
    
    def _split_into_sections(self, text: str, metadata: Dict) -> List[Dict]:
        """
        Split document into sections based on headers
        
        Detects patterns like:
        - "Section 5.2.3"
        - "5.2.3 Temperature Control"
        - "SECTION 5: QUALITY MANAGEMENT"
        """
        sections = []
        
        # Regex patterns for section headers
        patterns = [
            r'(?:Section|SECTION)\s+(\d+(?:\.\d+)*)\s*[:\-]?\s*(.+)',
            r'(\d+(?:\.\d+)+)\s+(.+)',
            r'([A-Z][A-Z\s]{3,})',  # ALL CAPS headers
        ]
        
        # Try to split by sections
        current_section = None
        current_content = []
        
        for line in text.split('\n'):
            # Check if this is a section header
            is_header = False
            for pattern in patterns:
                match = re.match(pattern, line.strip())
                if match:
                    # Save previous section
                    if current_section:
                        sections.append({
                            'regulation_id': metadata.get('regulation_id'),
                            'section': current_section,
                            'title': current_section,
                            'content': '\n'.join(current_content).strip(),
                            'metadata': metadata
                        })
                    
                    # Start new section
                    if len(match.groups()) >= 2:
                        current_section = f"{match.group(1)} - {match.group(2)}"
                    else:
                        current_section = match.group(1)
                    
                    current_content = []
                    is_header = True
                    break
            
            if not is_header:
                current_content.append(line)
        
        # Add final section
        if current_section and current_content:
            sections.append({
                'regulation_id': metadata.get('regulation_id'),
                'section': current_section,
                'title': current_section,
                'content': '\n'.join(current_content).strip(),
                'metadata': metadata
            })
        
        # If no sections detected, treat entire document as one section
        if not sections:
            sections = [{
                'regulation_id': metadata.get('regulation_id'),
                'section': 'Full Document',
                'title': metadata.get('regulation_name', 'Unknown'),
                'content': text,
                'metadata': metadata
            }]
        
        return sections
    
    def _chunk_text(self, text: str, section_metadata: Dict) -> List[Dict]:
        # split text into overlapping chunks
        chunks = []
        words = text.split()
        
        for i in range(0, len(words), self.chunk_size - self.chunk_overlap):
            chunk_words = words[i:i + self.chunk_size]
            chunk_text = ' '.join(chunk_words)
            
            # skip small chunks
            if len(chunk_text.strip()) < 50:  
                continue
            
            chunks.append({
                'regulation_id': section_metadata['regulation_id'],
                'section': section_metadata['section'],
                'title': section_metadata['title'],
                'content': chunk_text,
                'metadata': section_metadata['metadata'],
                'chunk_index': len(chunks)
            })
        
        return chunks