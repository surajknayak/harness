import io
import re
from logger import log_event

MAX_TEXT_CHARS = 500_000
MAX_PDF_PAGES = 50

STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "because", "as", "what",
    "which", "this", "that", "these", "those", "then", "just", "so", "than",
    "such", "both", "through", "about", "for", "is", "of", "while", "during",
    "to", "from", "in", "out", "on", "off", "again", "further", "then", "once",
    "here", "there", "when", "where", "why", "how", "all", "any", "both", "each",
    "few", "more", "most", "other", "some", "such", "no", "nor", "not", "only",
    "own", "same", "so", "than", "too", "very", "s", "t", "can", "will", "don",
    "should", "now", "are", "was", "were", "been", "being", "have", "has", "had",
    "do", "does", "did", "doing", "would", "could", "tell", "me", "show",
}

def extract_text_from_file(file_bytes: bytes, filename: str) -> dict:
    """
    Extracts text from .txt or .pdf files.
    Handles scanned/empty PDFs cleanly without raising raw errors.
    Truncates oversized files to protect memory.
    """
    fname_lower = filename.lower()
    log_event(f"Starting text extraction for file: {filename} ({len(file_bytes)} bytes)")
    
    try:
        extracted = ""
        if fname_lower.endswith(".pdf"):
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            total_pages = len(reader.pages)
            pages_to_read = min(total_pages, MAX_PDF_PAGES)
            
            page_texts = []
            for i in range(pages_to_read):
                p_text = reader.pages[i].extract_text() or ""
                if p_text.strip():
                    page_texts.append(p_text.strip())
            
            extracted = "\n\n".join(page_texts).strip()
            
            if not extracted:
                msg = f"The PDF '{filename}' contains no extractable text (it appears to be a scanned image or empty)."
                log_event(msg, level="warning")
                return {"text": "", "error": msg, "filename": filename, "chunks": []}
                
        elif fname_lower.endswith(".txt"):
            try:
                extracted = file_bytes.decode("utf-8").strip()
            except UnicodeDecodeError:
                extracted = file_bytes.decode("latin-1", errors="replace").strip()
                
            if not extracted:
                msg = f"The text file '{filename}' is empty."
                log_event(msg, level="warning")
                return {"text": "", "error": msg, "filename": filename, "chunks": []}
        else:
            msg = f"Unsupported file type for document RAG: '{filename}'. Only .txt and .pdf are supported."
            log_event(msg, level="warning")
            return {"text": "", "error": msg, "filename": filename, "chunks": []}

        # Truncate if exceptionally large
        if len(extracted) > MAX_TEXT_CHARS:
            extracted = extracted[:MAX_TEXT_CHARS]
            log_event(f"Document truncated to {MAX_TEXT_CHARS} characters.", level="warning")

        chunks = chunk_text(extracted, chunk_size=800, overlap=100)
        log_event(f"Extraction successful: {len(extracted)} chars, generated {len(chunks)} chunks for {filename}.")
        return {"text": extracted, "error": None, "filename": filename, "chunks": chunks}

    except Exception as exc:
        err_msg = f"Failed to extract document '{filename}': {str(exc)}"
        log_event(err_msg, level="error")
        return {"text": "", "error": err_msg, "filename": filename, "chunks": []}

def chunk_text(text: str, chunk_size: int = 800, overlap: int = 100) -> list[str]:
    """Splits text into chunks of 800 chars with 100 chars overlap."""
    if not text:
        return []
    
    step = max(1, chunk_size - overlap)
    chunks = []
    for i in range(0, len(text), step):
        chunk = text[i : i + chunk_size].strip()
        if chunk:
            chunks.append(chunk)
            
    return chunks

def retrieve_relevant_chunks(query: str, chunks: list[str], top_k: int = 4) -> list[str]:
    """
    Keyword relevance retrieval without an external vector DB.
    Scores chunks based on query keyword frequencies and term diversity.
    """
    if not chunks:
        return []

    # Tokenize query keywords
    tokens = re.findall(r"[a-zA-Z0-9]+", query.lower())
    keywords = [t for t in tokens if len(t) >= 3 and t not in STOPWORDS]

    log_event(f"Document RAG retrieval initiated for query: '{query}' with keywords: {keywords}")

    if not keywords:
        # Fallback to initial chunks if query has no specific keywords
        return chunks[:min(top_k, len(chunks))]

    scored_chunks = []
    for chunk in chunks:
        chunk_lower = chunk.lower()
        score = 0
        matched_terms = 0
        
        for kw in keywords:
            count = chunk_lower.count(kw)
            if count > 0:
                score += count
                matched_terms += 1
                
        # Bonus for chunks matching multiple distinct query keywords
        if matched_terms > 1:
            score += (matched_terms * 3)

        if score > 0:
            scored_chunks.append((score, chunk))

    scored_chunks.sort(key=lambda x: x[0], reverse=True)
    
    if scored_chunks:
        selected = [chunk for _, chunk in scored_chunks[:top_k]]
        log_event(f"RAG retrieval found {len(scored_chunks)} matching chunks. Selected top {len(selected)}.")
        return selected
    
    # If no exact keyword matches, return top chunk as general context
    log_event("No keyword matches found in chunks; providing document beginning as context.")
    return chunks[:min(2, len(chunks))]

def format_rag_context(chunks: list[str], filename: str = "Uploaded Document") -> str:
    """Formats retrieved chunks into grounded context string."""
    if not chunks:
        return ""
    
    header = f"=== RELEVANT CONTEXT FROM UPLOADED DOCUMENT: {filename} ===\n"
    body = "\n\n".join(f"[Excerpt {i}]:\n{c}" for i, c in enumerate(chunks, 1))
    return f"{header}{body}\n=== END DOCUMENT CONTEXT ==="
