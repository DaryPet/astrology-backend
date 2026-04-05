import fitz
import ebooklib
from ebooklib import epub
from docx import Document
from bs4 import BeautifulSoup
from langdetect import detect, LangDetectException
import os


def parse_file(file_path: str) -> dict:
    """
    Universal book parser.
    Returns: { text, language, format }
    """
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        text = parse_pdf(file_path)
    elif ext == ".epub":
        text = parse_epub(file_path)
    elif ext == ".docx":
        text = parse_docx(file_path)
    elif ext == ".txt":
        text = parse_txt(file_path)
    else:
        raise ValueError(f"Format {ext} is not supported")

    try:
        language = detect(text[:1000])
    except LangDetectException:
        language = "en"

    return {
        "text": text,
        "language": language,
        "format": ext
    }


def parse_pdf(path: str) -> str:
    doc = fitz.open(path)
    pages_text = []
    for page in doc:
        text = page.get_text()
        if text.strip():
            pages_text.append(text)
    doc.close()
    return "\n".join(pages_text)


def parse_epub(path: str) -> str:
    book = epub.read_epub(path)
    texts = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        soup = BeautifulSoup(item.content, "html.parser")
        text = soup.get_text()
        if text.strip():
            texts.append(text)
    return "\n".join(texts)


def parse_docx(path: str) -> str:
    doc = Document(path)
    paragraphs = []
    for p in doc.paragraphs:
        text = p.text.strip()
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs)


def parse_txt(path: str) -> str:
    for encoding in ["utf-8", "cp1251", "latin-1"]:
        try:
            with open(path, "r", encoding=encoding) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    raise ValueError("Could not determine file encoding")