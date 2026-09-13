# SmartMetriQ ML Training Pipeline

This training folder adds a lightweight machine-learning enhancement to the existing SmartMetriQ OCR pipeline.

## Goal

The ML component is used only to detect text or label regions in packaged commodity images. It does not decide legal compliance.

The existing Legal Metrology rule engine remains the final decision layer.

## Pipeline

Product Image -> Image Processing -> ML Text/Label Region Detection -> OCR -> Field Extraction -> Legal Metrology Rule Engine -> PASS / REVIEW / POTENTIAL VIOLATION

## Notes

- The initial dataset is the Kaggle dataset: dataclusterlabs/product-description-image-englishhindi-ocr.
- The model is intended for English/Hindi text-region detection and is not used to make legal compliance decisions.
- Kannada support continues to rely on the existing Tesseract OCR pipeline.
- If a trained model is unavailable, the application falls back to the standard OCR workflow automatically.
