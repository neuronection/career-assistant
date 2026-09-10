"""CV source processing: text layer first, OCR as fallback.

The original upload is never modified; per-page text plus derived page
images land in the validated `CvSourceExtraction` payload stored on the
documents row. OCR prefers vision-capable AI providers (works with local
multimodal models); an opt-in local tesseract is the no-AI fallback.
"""

import hashlib
import io
import shutil
import subprocess
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.gateway import ainvoke_structured, register_mock_fixture
from app.core.config import settings
from app.core.errors import NotFoundError
from app.models.document_model import Document
from app.models.enums import AITaskType, CvPageTextSource, DocumentStatus
from app.schemas.cv import CvSourceExtraction, CvSourcePage, OcrPagesResult

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
OCR_BATCH_PAGES = 4
RASTER_SCALE = 150 / 72
TESSERACT_CONFIDENCE = 0.6


def content_sha256(data: bytes) -> str:
    """Canonical file hash: raw bytes, hex digest."""
    return hashlib.sha256(data).hexdigest()


def source_file_path(document: Document) -> Path:
    """Stored path of the original upload (byte-exact, never rewritten)."""
    suffix = Path(document.filename).suffix or ".bin"
    return Path(settings.UPLOAD_DIR) / f"{document.id}{suffix}"


def derived_dir(document_id: uuid.UUID) -> Path:
    """Directory of derived page images for one source document."""
    return Path(settings.UPLOAD_DIR) / "derived" / str(document_id)


def page_image_path(document_id: uuid.UUID, index: int) -> Path:
    return derived_dir(document_id) / f"page-{index}.png"


def read_source_bytes(document: Document) -> bytes:
    path = source_file_path(document)
    if not path.exists():
        raise NotFoundError("Stored file missing")
    return path.read_bytes()


def extract_text_layer(document: Document) -> list[CvSourcePage]:
    """Per-page text from the embedded layer (empty pages need OCR)."""
    raw = read_source_bytes(document)
    suffix = Path(document.filename).suffix.lower()
    if document.mime == "application/pdf" or suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw))
        return [
            CvSourcePage(
                index=index,
                text=(page.extract_text() or "").strip(),
                source=CvPageTextSource.TEXT_LAYER.value,
            )
            for index, page in enumerate(reader.pages)
        ]
    if suffix in IMAGE_SUFFIXES:
        return [
            CvSourcePage(
                index=0,
                text="",
                source=CvPageTextSource.TEXT_LAYER.value,
            )
        ]
    return [
        CvSourcePage(
            index=0,
            text=raw.decode("utf-8", errors="replace").strip(),
            source=CvPageTextSource.TEXT_LAYER.value,
        )
    ]


def is_image_document(document: Document) -> bool:
    return Path(document.filename).suffix.lower() in IMAGE_SUFFIXES


def rasterize_missing_pages(
    document: Document, pages: list[CvSourcePage]
) -> dict[int, Path]:
    """Render pages without recoverable text to PNG (PDF: pypdfium2,
    image upload: the original bytes itself)."""
    targets = {page.index for page in pages if not page.text}
    if not targets:
        return {}
    derived_dir(document.id).mkdir(parents=True, exist_ok=True)
    if is_image_document(document):
        target = page_image_path(document.id, 0)
        target.write_bytes(read_source_bytes(document))
        return {0: target}
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(read_source_bytes(document))
    rendered: dict[int, Path] = {}
    for index in targets:
        if index >= len(pdf):
            continue
        bitmap = pdf[index].render(scale=RASTER_SCALE)
        image = bitmap.to_pil()
        path = page_image_path(document.id, index)
        image.save(path, format="PNG")
        rendered[index] = path
    pdf.close()
    return rendered


def tesseract_available() -> bool:
    return (
        bool(settings.OCR_TESSERACT_ENABLED) and shutil.which("tesseract") is not None
    )


def _tesseract_ocr(image_path: Path) -> str:
    result = subprocess.run(  # noqa: S603 - fixed binary, no shell
        ["tesseract", str(image_path), "stdout", "--psm", "3"],
        capture_output=True,
        timeout=60,
        check=False,
    )
    return result.stdout.decode("utf-8", errors="replace").strip()


def _ocr_user_prompt(batch: list[tuple[int, Path]]) -> str:
    lines = [
        "Extract every text fragment from the attached CV page images, "
        "preserving reading order. Each image is tagged below."
    ]
    for index, _path in batch:
        lines.append(f"[PAGE {index}] attached image {len(lines)}.")
    return "\n".join(lines)


def _mock_ocr_fixture(schema: type, user_prompt: str) -> dict:
    """Deterministic offline OCR output keyed on the [PAGE n] markers."""
    pages = []
    for line in user_prompt.splitlines():
        if line.startswith("[PAGE "):
            index = int(line.removeprefix("[PAGE ").split("]")[0])
            pages.append(
                {
                    "index": index,
                    "text": f"[ocr] page {index} recovered text",
                    "confidence": 0.75,
                }
            )
    return {"pages": pages}


async def _vision_ocr(
    db: AsyncSession,
    user_id: uuid.UUID,
    batch: list[tuple[int, Path]],
) -> list[CvSourcePage]:
    images = [("image/png", path.read_bytes()) for _index, path in batch]
    result = await ainvoke_structured(
        db,
        AITaskType.CV_OCR,
        OcrPagesResult,
        system=(
            "You transcribe document page images. Return every readable text "
            "fragment per page in reading order. Never invent content."
        ),
        user=_ocr_user_prompt(batch),
        user_id=user_id,
        images=images,
    )
    return [
        CvSourcePage(
            index=page.index,
            text=page.text.strip(),
            source=CvPageTextSource.OCR_VISION.value,
            confidence=page.confidence,
            image_path=str(batch[0][1].parent / f"page-{page.index}.png"),
        )
        for page in result.pages
    ]


async def run_ocr(
    db: AsyncSession,
    user_id: uuid.UUID,
    image_paths: dict[int, Path],
) -> tuple[list[CvSourcePage], dict]:
    """OCR the textless pages (vision batches first, tesseract fallback)."""
    engine: dict = {"ocr": "none"}
    if tesseract_available():
        ocr_pages = []
        for index, path in image_paths.items():
            text = _tesseract_ocr(path)
            ocr_pages.append(
                CvSourcePage(
                    index=index,
                    text=text,
                    source=CvPageTextSource.OCR_TESSERACT.value,
                    confidence=TESSERACT_CONFIDENCE if text else 0.0,
                    image_path=str(path),
                )
            )
        engine = {"ocr": "tesseract"}
        return ocr_pages, engine
    ordered = sorted(image_paths.items())
    ocr_pages: list[CvSourcePage] = []
    for start in range(0, len(ordered), OCR_BATCH_PAGES):
        batch = ordered[start : start + OCR_BATCH_PAGES]
        ocr_pages.extend(await _vision_ocr(db, user_id, batch))
    engine = {"ocr": "vision"}
    return ocr_pages, engine


async def process_cv_document(
    db: AsyncSession,
    document_id: uuid.UUID,
    user_id: uuid.UUID,
    force_ocr: bool = False,
) -> Document:
    """Full extraction pass: text layer, then OCR fallback for gaps.

    With `force_ocr` every renderable page goes through OCR (reparse path
    after a vision provider or tesseract becomes available).
    """
    document = await _owned_document(db, document_id, user_id)
    document.status = DocumentStatus.PROCESSING.value
    await db.commit()
    try:
        raw = read_source_bytes(document)
        pages = extract_text_layer(document)
        renderable = document.mime == "application/pdf" or Path(
            document.filename
        ).suffix.lower() in IMAGE_SUFFIXES | {".pdf"}
        needs_ocr = renderable and (force_ocr or any(not page.text for page in pages))
        ocr_used = False
        engine: dict = {"ocr": "none"}
        if needs_ocr:
            image_paths = rasterize_missing_pages(document, pages)
            if image_paths:
                ocr_pages, engine = await run_ocr(db, user_id, image_paths)
                merged = {page.index: page for page in pages if page.text}
                for page in ocr_pages:
                    existing = merged.get(page.index)
                    if existing is None or not existing.text:
                        merged[page.index] = page
                ocr_used = any(
                    page.source != CvPageTextSource.TEXT_LAYER.value
                    for page in merged.values()
                )
                pages = [merged[index] for index in sorted(merged)]
        for page in pages:
            if page.image_path is None and not page.text:
                path = page_image_path(document.id, page.index)
                if path.exists():
                    page.image_path = str(path)
        extraction = CvSourceExtraction(
            pages=pages,
            full_text="\n\n".join(page.text for page in pages if page.text),
            has_text_layer=any(
                page.source == CvPageTextSource.TEXT_LAYER.value and page.text
                for page in pages
            ),
            ocr_used=ocr_used,
            content_sha256=content_sha256(raw),
            engine=engine,
        )
        document.page_count = len(pages)
        document.extraction = extraction.model_dump(mode="json")
        document.status = DocumentStatus.READY.value
        document.error = ""
    except Exception as exc:  # noqa: BLE001 - job pipeline must record failure
        document.status = DocumentStatus.FAILED.value
        document.error = str(exc)[:500]
    db.add(document)
    await db.commit()
    await db.refresh(document)
    return document


async def _owned_document(
    db: AsyncSession, document_id: uuid.UUID, user_id: uuid.UUID
) -> Document:
    from sqlalchemy import select

    rows = await db.execute(
        select(Document).where(Document.id == document_id, Document.user_id == user_id)
    )
    document = rows.scalars().first()
    if document is None:
        raise NotFoundError("Document not found")
    return document


def cv_extraction_of(document: Document) -> CvSourceExtraction | None:
    """Validated CV extraction payload for a document (None when absent)."""
    if document.kind != "cv" or not document.extraction:
        return None
    return CvSourceExtraction.model_validate(document.extraction)


register_mock_fixture(AITaskType.CV_OCR, _mock_ocr_fixture)
