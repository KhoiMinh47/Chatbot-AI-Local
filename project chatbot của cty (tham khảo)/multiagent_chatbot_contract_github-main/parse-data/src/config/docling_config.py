"""
Module cấu hình Docling DocumentConverter.

Khởi tạo singleton DocumentConverter với GPU acceleration (CUDA)
để tối ưu hiệu năng parse PDF và OCR ảnh trong production.
"""

import logging

from docling.document_converter import DocumentConverter, PdfFormatOption, ImageFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, EasyOcrOptions
from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions


# Cấu hình logging cho module này
logger = logging.getLogger(__name__)


def create_converter() -> DocumentConverter:
    """
    Khởi tạo DocumentConverter với cấu hình GPU acceleration.

    Input: Không có
    Output: DocumentConverter - instance đã cấu hình sẵn

    Hỗ trợ:
    - PDF, DOCX, PPTX, CSV (parse text/bảng)
    - IMAGE: JPG, PNG, BMP, TIFF (OCR bằng EasyOCR, hỗ trợ tiếng Việt)

    Sử dụng AcceleratorDevice.AUTO để tự động detect:
    - CUDA (NVIDIA GPU) nếu có → hiệu năng cao nhất
    - CPU nếu không có GPU → fallback an toàn
    """

    # AUTO sẽ tự chọn CUDA nếu có GPU, nếu không sẽ dùng CPU
    accelerator_options = AcceleratorOptions(
        device=AcceleratorDevice.AUTO,
        num_threads=2  # giảm từ 4→2: ít RAM hơn, ít spawn worker hơn
    )

    # --- Cấu hình OCR cho ảnh (EasyOCR hỗ trợ tiếng Việt tốt) ---
    ocr_options = EasyOcrOptions(
        lang=["vi", "en"],  # Hỗ trợ cả tiếng Việt và tiếng Anh
    )

    # --- Pipeline cho PDF: thiết lập OCR cho tiếng Việt, tắt generate ảnh để tiết kiệm RAM ---
    pdf_pipeline_options = PdfPipelineOptions()
    pdf_pipeline_options.accelerator_options = accelerator_options
    pdf_pipeline_options.do_ocr = True
    pdf_pipeline_options.ocr_options = ocr_options
    pdf_pipeline_options.generate_page_images = False
    pdf_pipeline_options.generate_picture_images = False

    # --- Pipeline cho IMAGE: bật OCR, force full page OCR ---
    image_pipeline_options = PdfPipelineOptions()
    image_pipeline_options.accelerator_options = accelerator_options
    image_pipeline_options.do_ocr = True
    image_pipeline_options.ocr_options = ocr_options
    image_pipeline_options.generate_page_images = False
    image_pipeline_options.generate_picture_images = False

    # Khởi tạo converter với cả PDF và IMAGE format
    converter = DocumentConverter(
        allowed_formats=[
            InputFormat.PDF,
            InputFormat.DOCX,
            InputFormat.PPTX,
            InputFormat.CSV,
            InputFormat.IMAGE,
        ],
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_pipeline_options),
            InputFormat.IMAGE: ImageFormatOption(pipeline_options=image_pipeline_options),
        },
    )

    # Log thông tin device để dễ debug khi deploy
    logger.info(
        "DocumentConverter khởi tạo: AUTO device, 2 threads, "
        "IMAGE OCR enabled (EasyOCR vi+en)"
    )

    return converter


# Singleton - chỉ khởi tạo 1 lần khi import module
document_converter = create_converter()
