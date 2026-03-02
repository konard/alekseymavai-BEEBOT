"""Build the knowledge base from all available sources."""

import logging

from src.pdf_loader import process_all_pdfs
from src.youtube_loader import download_all_subtitles
from src.knowledge_base import KnowledgeBase
from src.config import SUBTITLES_DIR

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def build():
    documents = []

    # 1. PDF documents
    logger.info("Extracting text from PDFs...")
    pdf_docs = process_all_pdfs()
    documents.extend(pdf_docs)
    logger.info(f"  PDFs: {len(pdf_docs)} documents")

    # 2. YouTube subtitles (if available or can download)
    existing_subs = list(SUBTITLES_DIR.glob("*.txt")) if SUBTITLES_DIR.exists() else []
    if existing_subs:
        logger.info(f"Loading {len(existing_subs)} existing subtitle files...")
        for txt_path in existing_subs:
            text = txt_path.read_text(encoding="utf-8")
            if len(text) > 50:
                documents.append({
                    "source": f"youtube:{txt_path.stem}",
                    "text": text,
                    "path": str(txt_path),
                })
    else:
        logger.info("Attempting to download YouTube subtitles...")
        try:
            yt_docs = download_all_subtitles()
            documents.extend(yt_docs)
            logger.info(f"  YouTube: {len(yt_docs)} videos")
        except Exception as e:
            logger.warning(f"Could not download subtitles: {e}")
            logger.info("Continuing with PDF-only knowledge base")

    if not documents:
        logger.error("No documents found! Cannot build knowledge base.")
        return

    # 3. Build FAISS index
    logger.info(f"Building knowledge base from {len(documents)} documents...")
    kb = KnowledgeBase()
    n_chunks = kb.build(documents)
    logger.info(f"Knowledge base built: {n_chunks} chunks indexed")

    # 4. Test search
    test_query = "Как принимать настойку прополиса?"
    results = kb.search(test_query, top_k=3)
    logger.info(f"\nTest search: '{test_query}'")
    for r in results:
        logger.info(f"  [{r['score']:.3f}] ({r['source']}) {r['text'][:100]}...")


if __name__ == "__main__":
    build()
