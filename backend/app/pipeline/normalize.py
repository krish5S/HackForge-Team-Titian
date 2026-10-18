from pathlib import Path

import cv2
import numpy as np


def load_image(image_path: str | Path) -> np.ndarray:
    """Load an image from disk as a BGR image."""
    if Path(image_path).suffix.lower() == ".pdf":
        import pypdfium2 as pdfium

        document = pdfium.PdfDocument(str(image_path))
        try:
            if len(document) == 0:
                raise ValueError(f"PDF has no pages: {image_path}")
            page = document[0]
            try:
                rendered = page.render(scale=2).to_pil().convert("RGB")
                return cv2.cvtColor(np.asarray(rendered), cv2.COLOR_RGB2BGR)
            finally:
                page.close()
        finally:
            document.close()
    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError(f"Could not read image: {image_path}")
    return image


def correct_perspective(image: np.ndarray) -> np.ndarray:
    """
    Attempt perspective correction when a clear four-corner receipt
    contour can be detected. Otherwise, return the original image.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)

    contours, _ = cv2.findContours(
        edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE
    )
    contours = sorted(contours, key=cv2.contourArea, reverse=True)

    height, width = image.shape[:2]
    for contour in contours[:10]:
        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * perimeter, True)

        if len(approx) != 4 or cv2.contourArea(approx) < 0.15 * height * width:
            continue

        points = approx.reshape(4, 2).astype(np.float32)

        # Order corners: top-left, top-right, bottom-right, bottom-left.
        sums = points.sum(axis=1)
        differences = np.diff(points, axis=1).ravel()
        ordered = np.array(
            [
                points[np.argmin(sums)],
                points[np.argmin(differences)],
                points[np.argmax(sums)],
                points[np.argmax(differences)],
            ],
            dtype=np.float32,
        )

        tl, tr, br, bl = ordered
        out_width = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
        out_height = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))

        if out_width < 100 or out_height < 100:
            continue

        destination = np.array(
            [
                [0, 0],
                [out_width - 1, 0],
                [out_width - 1, out_height - 1],
                [0, out_height - 1],
            ],
            dtype=np.float32,
        )

        matrix = cv2.getPerspectiveTransform(ordered, destination)
        return cv2.warpPerspective(image, matrix, (out_width, out_height))

    return image


def deskew(image: np.ndarray) -> np.ndarray:
    """Correct small rotations using foreground pixels."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    threshold = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )[1]

    coordinates = cv2.findNonZero(threshold)
    if coordinates is None or len(coordinates) < 20:
        return image

    angle = cv2.minAreaRect(coordinates)[-1]
    if angle < -45:
        angle = 90 + angle
    elif angle > 45:
        angle = angle - 90

    # Avoid aggressive rotation when background objects distort the estimate.
    if abs(angle) > 15:
        return image

    height, width = image.shape[:2]
    center = (width // 2, height // 2)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)

    return cv2.warpAffine(
        image,
        matrix,
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255),
    )


def enhance_contrast(image: np.ndarray) -> np.ndarray:
    """Apply CLAHE to the luminance channel while preserving color."""
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    lightness, a, b = cv2.split(lab)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced_lightness = clahe.apply(lightness)

    return cv2.cvtColor(
        cv2.merge((enhanced_lightness, a, b)),
        cv2.COLOR_LAB2BGR,
    )


def denoise(image: np.ndarray) -> np.ndarray:
    """Reduce mild camera noise while retaining text edges."""
    return cv2.fastNlMeansDenoisingColored(
        image,
        None,
        h=5,
        hColor=5,
        templateWindowSize=7,
        searchWindowSize=21,
    )


def normalize_receipt(image_path: str | Path) -> np.ndarray:
    """Run the initial receipt normalization pipeline."""
    image = load_image(image_path)
    image = correct_perspective(image)
    image = deskew(image)
    image = enhance_contrast(image)
    image = denoise(image)
    return image


def save_normalized(
    input_path: str | Path,
    output_path: str | Path,
) -> Path:
    """Normalize an image and save the result."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    image = normalize_receipt(input_path)
    if not cv2.imwrite(str(output), image):
        raise OSError(f"Could not save normalized image: {output}")

    return output


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Normalize a receipt image.")
    parser.add_argument("input", help="Path to input receipt image")
    parser.add_argument("output", help="Path for normalized output image")
    args = parser.parse_args()

    result = save_normalized(args.input, args.output)
    print(f"Normalized receipt saved to: {result.resolve()}")
