from typing import Any

from ..pdf_parser.base import (
    DocumentParser,
    LocalParsing,
    ParsedTextSegment,
    ParseResult,
    SegmentedTextResult,
    TextParsing,
)


class PyPdfParser(DocumentParser, TextParsing, SegmentedTextResult, LocalParsing):
    """使用 PyPDFLoader 从 PDF 中提取文本（仅文本）。"""

    # Basic PDF-only support
    supported_extensions = [".pdf"]

    async def _parse_impl(self, file_path: str, **kwargs: Any) -> ParseResult:
        return await extract_text_with_pypdf(file_path, **kwargs)


class PdfPlumberParser(DocumentParser, TextParsing, SegmentedTextResult, LocalParsing):
    """使用 pdfplumber 从 PDF 中提取文本（仅文本）。"""

    # Basic PDF-only support
    supported_extensions = [".pdf"]

    async def _parse_impl(self, file_path: str, **kwargs: Any) -> ParseResult:
        return await extract_text_with_pdfplumber(file_path, **kwargs)


class UnstructuredParser(
    DocumentParser, TextParsing, SegmentedTextResult, LocalParsing
):
    """使用 Unstructured 从现代 Office/文本格式中提取文本。

    注意：
        - 现代 Open XML 格式（如 .docx、.pptx、.xlsx）可直接支持。
        - 旧格式 .doc 和 .ppt 仅当已安装 LibreOffice 时才支持。
    """

    # Unstructured supports multiple modern office/text formats; .doc/.ppt support is conditional on LibreOffice.
    supported_extensions = [
        ".pdf",
        ".docx",
        ".doc",
        ".pptx",
        ".ppt",
        ".xlsx",
        ".xls",
        ".txt",
        ".md",
        ".json",
        ".html",
    ]

    async def _parse_impl(self, file_path: str, **kwargs: Any) -> ParseResult:
        return await extract_text_with_unstructured(file_path, **kwargs)


class PyMuPdfParser(DocumentParser, TextParsing, SegmentedTextResult, LocalParsing):
    """使用 PyMuPDF (fitz) 从 PDF 中提取文本（仅文本）。"""

    # Basic PDF-only support
    supported_extensions = [".pdf"]

    async def _parse_impl(self, file_path: str, **kwargs: Any) -> ParseResult:
        return await extract_text_with_pymupdf(file_path, **kwargs)


# Implementation functions
async def extract_text_with_pypdf(file_path: str, **kwargs: Any) -> ParseResult:
    """使用 PyPDFLoader 提取文本。"""
    if not file_path.lower().endswith(".pdf"):
        raise ValueError("PyPdfParser only supports PDF files.")
    try:
        from langchain_community.document_loaders import PyPDFLoader

        loader = PyPDFLoader(file_path)
        documents = loader.load()
        return _to_parsed_content_list(documents, file_path, "pypdf", **kwargs)

    except ImportError as e:
        raise RuntimeError(f"PyPDF dependencies not available: {e}") from e
    except Exception as e:
        raise RuntimeError(f"PyPDF text extraction failed: {e}") from e


async def extract_text_with_pdfplumber(file_path: str, **kwargs: Any) -> ParseResult:
    """使用 pdfplumber 提取文本。"""
    if not file_path.lower().endswith(".pdf"):
        raise ValueError("PdfPlumberParser only supports PDF files.")
    try:
        import pdfplumber

        segments: list[ParsedTextSegment] = []
        with pdfplumber.open(file_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                text = page.extract_text() or ""
                metadata = create_metadata(
                    source_path=file_path,
                    file_type="pdf",
                    parse_method="pdfplumber",
                    page_number=page_num,
                    **kwargs,
                )
                segments.append(ParsedTextSegment(text=text, metadata=metadata))

        return ParseResult(text_segments=segments)

    except ImportError as e:
        raise RuntimeError(f"PDFPlumber dependencies not available: {e}") from e
    except Exception as e:
        raise RuntimeError(f"PDFPlumber text extraction failed: {e}") from e


async def extract_text_with_unstructured(file_path: str, **kwargs: Any) -> ParseResult:
    """使用 Unstructured 提取文本（支持 PDF、DOCX、PPTX、XLSX 等格式）。

    注意：
        - 旧格式 .doc 和 .ppt 需要已安装 LibreOffice。
        - 为获得最佳兼容性，建议将旧版 Office 文件转换为 Open XML 格式（.docx/.pptx/.xlsx）。
    """

    try:
        from pathlib import Path

        # Determine file type and use appropriate partition function
        file_ext = Path(file_path).suffix.lower()

        # Use unstructured partition functions directly (no LibreOffice needed for modern formats)
        if file_ext == ".pdf":
            from unstructured.partition.pdf import partition_pdf

            elements = partition_pdf(filename=file_path)
        elif file_ext == ".docx":
            from unstructured.partition.docx import partition_docx

            elements = partition_docx(filename=file_path)
        elif file_ext == ".doc":
            # Legacy .doc format requires LibreOffice
            from unstructured.partition.doc import partition_doc

            try:
                elements = partition_doc(filename=file_path)
            except FileNotFoundError:
                raise RuntimeError(
                    "Legacy .doc files require LibreOffice to be installed. "
                    "Please convert to .docx format or install LibreOffice: "
                    "https://www.libreoffice.org/get-help/install-howto/"
                )
        elif file_ext == ".pptx":
            from unstructured.partition.pptx import partition_pptx

            elements = partition_pptx(filename=file_path)
        elif file_ext == ".ppt":
            # Legacy .ppt format requires LibreOffice
            from unstructured.partition.ppt import partition_ppt

            try:
                elements = partition_ppt(filename=file_path)
            except FileNotFoundError:
                raise RuntimeError(
                    "Legacy .ppt files require LibreOffice to be installed. "
                    "Please convert to .pptx format or install LibreOffice: "
                    "https://www.libreoffice.org/get-help/install-howto/"
                )
        elif file_ext in (".xlsx", ".xls"):
            from unstructured.partition.xlsx import partition_xlsx

            elements = partition_xlsx(filename=file_path)
        elif file_ext == ".html":
            from unstructured.partition.html import partition_html

            elements = partition_html(filename=file_path)
        elif file_ext in (".txt", ".md", ".json"):
            # For plain text files, read directly
            with open(file_path, "r", encoding="utf-8") as f:
                text_content = f.read()

            # Create a single text segment
            metadata = create_metadata(
                source_path=file_path,
                file_type=file_ext.lstrip("."),
                parse_method="unstructured",
                **kwargs,
            )
            return ParseResult(
                text_segments=[ParsedTextSegment(text=text_content, metadata=metadata)]
            )
        else:
            # For other file types, try auto partition
            from unstructured.partition.auto import partition

            elements = partition(filename=file_path)

        # Convert unstructured elements to ParseResult format
        segments: list[ParsedTextSegment] = []
        for element in elements:
            metadata = create_metadata(
                source_path=file_path,
                file_type=file_ext.lstrip("."),
                parse_method="unstructured",
                category=getattr(element, "category", None),
                element_id=getattr(element, "id", None),
                **kwargs,
            )
            segments.append(ParsedTextSegment(text=str(element), metadata=metadata))

        return ParseResult(text_segments=segments)

    except ImportError as e:
        error_msg = str(e)
        raise RuntimeError(
            f"Unstructured dependencies not available: {error_msg}\n\n"
            f"To fix this, try one of the following:\n"
            f"  1. Install document-processing dependencies: pip install -e '.[document-processing]'\n"
            f"  2. Or use the 'deepdoc' parser instead"
        ) from e

    except Exception as e:
        raise RuntimeError(f"Unstructured text extraction failed: {e}") from e


async def extract_text_with_pymupdf(file_path: str, **kwargs: Any) -> ParseResult:
    """使用 PyMuPDF (fitz) 提取文本。"""
    if not file_path.lower().endswith(".pdf"):
        raise ValueError("PyMuPdfParser only supports PDF files.")
    try:
        import fitz  # PyMuPDF

        segments: list[ParsedTextSegment] = []
        doc = fitz.open(file_path)
        try:
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                text = page.get_text()
                metadata = create_metadata(
                    source_path=file_path,
                    file_type="pdf",
                    parse_method="pymupdf",
                    page_number=page_num + 1,
                    **kwargs,
                )
                segments.append(ParsedTextSegment(text=text, metadata=metadata))
        finally:
            doc.close()

        return ParseResult(text_segments=segments)

    except ImportError as e:
        raise RuntimeError(f"PyMuPDF dependencies not available: {e}") from e
    except Exception as e:
        raise RuntimeError(f"PyMuPDF text extraction failed: {e}") from e


def create_metadata(
    source_path: str, file_type: str, parse_method: str, **extra: Any
) -> dict[str, Any]:
    """
    创建标准元数据字典。

    参数：
        source_path: 源文件路径
        file_type: 文件类型（例如 'pdf'、'docx'）
        parse_method: 使用的解析方法
        **extra: 额外的元数据字段

    返回：
        标准元数据字典
    """
    # Exclude progress_callback and other non-serializable objects from metadata
    filtered_extra = {
        key: value for key, value in extra.items() if key not in ("progress_callback",)
    }
    metadata = {
        "source": source_path,
        "file_type": file_type,
        "parse_method": parse_method,
        **filtered_extra,
    }
    return metadata


# 辅助函数：将 LangChain 风格的文档对象转换为 ParsedContent 列表
def _to_parsed_content_list(
    docs: list[Any], source_path: str, parse_method: str, **kwargs: Any
) -> ParseResult:
    """将 LangChain 风格的文档对象列表转换为 ParsedContent 列表。"""
    from pathlib import Path

    # Detect file type from extension
    file_ext = Path(source_path).suffix.lower()
    file_type_map = {
        ".pdf": "pdf",
        ".doc": "doc",
        ".docx": "docx",
        ".ppt": "ppt",
        ".pptx": "pptx",
        ".xlsx": "xlsx",
        ".xls": "xls",
    }
    file_type = file_type_map.get(file_ext, file_ext.lstrip("."))

    segments: list[ParsedTextSegment] = []
    for i, doc in enumerate(docs):
        # Use page number from metadata if available, else fallback to index
        page_num = doc.metadata.get("page", i + 1)
        metadata = create_metadata(
            source_path=source_path,
            file_type=file_type,
            parse_method=parse_method,
            page_number=page_num,
            **kwargs,
        )
        # Assume doc has page_content (standard in LangChain document loaders)
        if not hasattr(doc, "page_content"):
            raise ValueError(
                f"Document object does not have 'page_content': {type(doc)}"
            )
        segments.append(ParsedTextSegment(text=doc.page_content, metadata=metadata))
    return ParseResult(text_segments=segments)
