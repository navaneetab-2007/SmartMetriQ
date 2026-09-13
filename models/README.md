# SmartMetriQ ML Model Artifacts

This folder stores trained model files and evaluation metadata for the lightweight text-region detection pipeline.

## Current state

The project intentionally keeps the existing Tesseract OCR pipeline as the primary text extraction engine.

The ML model is optional and should only be used to detect useful text regions in product/package images.

## Example files

- text_detector_best_v1.pt
- evaluation_results.json
- model_version.json

The application automatically falls back to the standard OCR pipeline if no trained model is available.
