import json
import os
import random
import shutil
from pathlib import Path

from PIL import Image


RAW_DIR = Path(__file__).resolve().parents[1] / 'data' / 'raw'
PROCESSED_DIR = Path(__file__).resolve().parents[1] / 'data' / 'processed'
TRAIN_DIR = Path(__file__).resolve().parents[1] / 'data' / 'train'
VAL_DIR = Path(__file__).resolve().parents[1] / 'data' / 'validation'
TEST_DIR = Path(__file__).resolve().parents[1] / 'data' / 'test'


def clean_dir(path: Path):
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def is_valid_image(path: Path):
    try:
        with Image.open(path) as img:
            img.verify()
        return True
    except Exception:
        return False


def discover_images(raw_dir: Path):
    image_files = []
    if not raw_dir.exists():
        return image_files

    for file_path in sorted(raw_dir.rglob('*')):
        if file_path.is_file() and file_path.suffix.lower() in {'.png', '.jpg', '.jpeg', '.bmp', '.webp'}:
            if is_valid_image(file_path):
                image_files.append(file_path)
    return image_files


def split_images(images):
    random.Random(42).shuffle(images)
    total = len(images)
    train_count = max(1, int(total * 0.70))
    val_count = max(1, int(total * 0.15))
    test_count = total - train_count - val_count
    if test_count <= 0:
        test_count = max(1, total - train_count - val_count)
    if train_count + val_count + test_count != total:
        diff = total - (train_count + val_count + test_count)
        train_count += diff

    train_images = images[:train_count]
    val_images = images[train_count:train_count + val_count]
    test_images = images[train_count + val_count:train_count + val_count + test_count]
    return train_images, val_images, test_images


def prepare_dataset():
    clean_dir(PROCESSED_DIR)
    clean_dir(TRAIN_DIR)
    clean_dir(VAL_DIR)
    clean_dir(TEST_DIR)

    image_files = discover_images(RAW_DIR)
    print(f'Total images found in raw data: {len(image_files)}')

    train_images, val_images, test_images = split_images(image_files)
    for split_name, image_list in [('train', train_images), ('validation', val_images), ('test', test_images)]:
        target_dir = {'train': TRAIN_DIR, 'validation': VAL_DIR, 'test': TEST_DIR}[split_name]
        for src in image_list:
            target = target_dir / src.name
            shutil.copy2(src, target)

    summary = {
        'total_images': len(image_files),
        'train_images': len(train_images),
        'validation_images': len(val_images),
        'test_images': len(test_images),
    }

    with (PROCESSED_DIR / 'dataset_summary.json').open('w', encoding='utf-8') as fh:
        json.dump(summary, fh, indent=2)

    print('Dataset summary:')
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == '__main__':
    prepare_dataset()
