import json
import os
from pathlib import Path


MODEL_DIR = Path(__file__).resolve().parents[1] / 'models'
MODEL_DIR.mkdir(parents=True, exist_ok=True)


def get_latest_model_version():
    version_file = MODEL_DIR / 'model_version.json'
    if version_file.exists():
        try:
            with version_file.open('r', encoding='utf-8') as fh:
                data = json.load(fh)
            return int(data.get('version', 0)) + 1
        except Exception:
            return 1
    return 1


def save_model_metadata(version, metrics=None):
    payload = {
        'version': version,
        'model_name': 'text_detector_model',
        'model_path': str(MODEL_DIR / f'text_detector_best_v{version}.pt'),
        'training_date': __import__('datetime').datetime.now().isoformat(),
        'dataset': 'Product Description Image - English Hindi OCR',
        'metrics': metrics or {},
    }
    with (MODEL_DIR / 'model_version.json').open('w', encoding='utf-8') as fh:
        json.dump(payload, fh, indent=2)
    return payload


if __name__ == '__main__':
    version = get_latest_model_version()
    print(f'Training pipeline placeholder for model version v{version}')
    print('This project keeps the existing OCR system as the main inference pipeline.')
    print('A lightweight text-region detector can be added here in a future training run.')
    print('Model metadata saved at:', MODEL_DIR / 'model_version.json')
    save_model_metadata(version)
