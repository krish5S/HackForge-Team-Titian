import argparse
import json
from pathlib import Path

from backend.app.pipeline.normalize import save_normalized
from backend.app.pipeline.ocr import extract_text


def process_receipt(image_path: str, output_dir: str) -> dict:
    image_path = Path(image_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    normalized_path = output_dir / f"{image_path.stem}_normalized.jpg"
    ocr_output_path = output_dir / f"{image_path.stem}_ocr.json"

    # Step 1: Normalize the receipt image
    save_normalized(image_path, normalized_path)

    # Step 2: Extract text with OCR
    ocr_result = extract_text(str(normalized_path))

    # Step 3: Save structured OCR output
    with ocr_output_path.open("w", encoding="utf-8") as file:
        json.dump(ocr_result, file, indent=2, ensure_ascii=False)

    return {
        "input_image": str(image_path),
        "normalized_image": str(normalized_path),
        "ocr_output": str(ocr_output_path),
        "line_count": len(ocr_result.get("lines", [])),
        "full_text": ocr_result.get("full_text", ""),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Normalize a receipt and extract OCR text.")
    parser.add_argument("--image", required=True, help="Path to the receipt image")
    parser.add_argument(
        "--output-dir",
        default=str(Path.home() / "datasets" / "processed_receipts"),
        help="Directory for normalized images and OCR JSON",
    )
    args = parser.parse_args()

    result = process_receipt(args.image, args.output_dir)
    print(json.dumps(result, indent=2, ensure_ascii=False))
