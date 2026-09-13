import os
import sys
from pathlib import Path


def download_kaggle_dataset():
    try:
        import kagglehub
    except ImportError:
        raise RuntimeError(
            "kagglehub is not installed. Install it with: pip install kagglehub"
        )

    dataset_name = "dataclusterlabs/product-description-image-englishhindi-ocr"
    output_dir = Path(__file__).resolve().parents[1] / "data" / "raw"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Downloading dataset: {dataset_name}")
    print(f"Target directory: {output_dir}")

    try:
        path = kagglehub.dataset_download(dataset_name)
        downloaded = Path(path)
        print(f"Dataset downloaded to: {downloaded}")

        if downloaded.exists():
            for child in downloaded.iterdir():
                target = output_dir / child.name
                if target.exists():
                    continue
                if child.is_dir():
                    for inner in child.iterdir():
                        final_target = output_dir / inner.name
                        if not final_target.exists():
                            if inner.is_dir():
                                import shutil
                                shutil.copytree(inner, final_target)
                            else:
                                import shutil
                                shutil.copy2(inner, final_target)
                else:
                    import shutil
                    shutil.copy2(child, target)

            print("Download status: success")
            return str(output_dir)

        raise FileNotFoundError("Dataset download completed but the expected folder was not created.")

    except Exception as exc:
        print(f"Download status: failed")
        print(f"Error: {exc}")
        raise


if __name__ == "__main__":
    try:
        download_kaggle_dataset()
    except Exception as exc:
        print(f"Dataset download failed: {exc}")
        sys.exit(1)
