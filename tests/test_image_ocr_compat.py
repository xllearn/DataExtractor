import tempfile
import unittest
from pathlib import Path

import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class ImageOcrCompatibilityTests(unittest.TestCase):
    def _image_path(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        path = Path(temp_dir.name) / "sample.jpg"
        path.write_bytes(b"not a real image; fake engines do not read it")
        return path

    def test_legacy_paddleocr_tuple_result_is_supported(self):
        from image_ocr import recognize_image

        class LegacyEngine:
            def ocr(self, image, cls=True):
                return [
                    [
                        [[[0, 0], [1, 0], [1, 1], [0, 1]], ("outpatient fee", 0.99)],
                        [[[0, 2], [1, 2], [1, 3], [0, 3]], ["ratio 80%", 0.98]],
                    ]
                ]

        text = recognize_image(self._image_path(), engine=LegacyEngine())

        self.assertEqual(text.splitlines(), ["outpatient fee", "ratio 80%"])

    def test_paddleocr_3_rec_texts_result_is_supported_after_cls_retry(self):
        from image_ocr import recognize_image

        class PaddleOcr3Engine:
            def __init__(self):
                self.calls = []

            def ocr(self, image, **kwargs):
                self.calls.append(("ocr", kwargs))
                if "cls" in kwargs:
                    raise TypeError("PaddleOCR.predict() got an unexpected keyword argument 'cls'")
                return [{"rec_texts": ["deductible 500", "limit 400000"]}]

        engine = PaddleOcr3Engine()
        text = recognize_image(self._image_path(), engine=engine)

        self.assertEqual(text.splitlines(), ["deductible 500", "limit 400000"])
        self.assertEqual(engine.calls, [("ocr", {"cls": True}), ("ocr", {})])

    def test_predict_only_engine_rec_texts_result_is_supported(self):
        from image_ocr import recognize_image

        class PredictOnlyEngine:
            def predict(self, image):
                return [{"rec_texts": ["benefit A", "benefit B"]}]

        text = recognize_image(self._image_path(), engine=PredictOnlyEngine())

        self.assertEqual(text.splitlines(), ["benefit A", "benefit B"])


if __name__ == "__main__":
    unittest.main()
