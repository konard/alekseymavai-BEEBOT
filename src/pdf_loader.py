"""Extract text from PDF instruction files."""

from pathlib import Path
from PyPDF2 import PdfReader

from src.config import BASE_DIR, TEXTS_DIR


def extract_pdf_text(pdf_path: Path) -> str:
    """Extract all text from a PDF file."""
    reader = PdfReader(str(pdf_path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages).strip()


def process_all_pdfs(pdf_dir: Path | None = None) -> list[dict]:
    """Extract text from all PDF files in the project root."""
    pdf_dir = pdf_dir or BASE_DIR
    TEXTS_DIR.mkdir(parents=True, exist_ok=True)

    results = []
    for pdf_path in sorted(pdf_dir.glob("*.pdf")):
        text = extract_pdf_text(pdf_path)
        if len(text) > 50:
            txt_path = TEXTS_DIR / f"{pdf_path.stem}.txt"
            txt_path.write_text(text, encoding="utf-8")
            results.append({
                "filename": pdf_path.name,
                "source": f"pdf:{pdf_path.stem}",
                "text": text,
                "path": str(txt_path),
            })

    return results


if __name__ == "__main__":
    docs = process_all_pdfs()
    print(f"Extracted text from {len(docs)} PDFs")
    for doc in docs:
        print(f"  {doc['filename']}: {len(doc['text'])} chars")
