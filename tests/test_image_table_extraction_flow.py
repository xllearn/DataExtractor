import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class ImageTableExtractionFlowTests(unittest.TestCase):
    def _parsed(self, tables_text="", image_urls=None, clean_text="正文"):
        from html_parser import ParsedHtml

        return ParsedHtml(clean_text=clean_text, tables_text=tables_text, image_urls=image_urls or [])

    def _field_mapping(self):
        from field_mapping import load_field_mapping

        return load_field_mapping(None)

    def test_html_table_skips_vision_and_ocr(self):
        from image_table_pipeline import collect_image_table_context

        class FailingVision:
            model = "fake"

            def is_ready(self):
                return True

            def extract_image_table(self, *_args, **_kwargs):
                raise AssertionError("vision should not be called")

        def failing_ocr(*_args, **_kwargs):
            raise AssertionError("ocr should not be called")

        with tempfile.TemporaryDirectory() as tmp:
            context = collect_image_table_context(
                parsed=self._parsed(tables_text="| 类型 |\n| --- |\n| 门诊 |", image_urls=["a.jpg"]),
                record={},
                record_index=1,
                temp_images_dir=Path(tmp),
                today="20260701",
                field_mapping=self._field_mapping(),
                ocr_enabled=True,
                ocr_func=failing_ocr,
                vision_client=FailingVision(),
            )

        self.assertFalse(context.vision_triggered)
        self.assertFalse(context.ocr_triggered)

    def test_external_ocr_has_highest_priority_and_parses_records(self):
        from image_table_pipeline import collect_image_table_context

        class FailingVision:
            def is_ready(self):
                return True

            def extract_image_table(self, *_args, **_kwargs):
                raise AssertionError("vision should not be called when external OCR text is supplied")

        with tempfile.TemporaryDirectory() as tmp:
            context = collect_image_table_context(
                parsed=self._parsed(image_urls=["a.jpg"]),
                record={"Title": "普惠门诊保·如意版2025 保障详情"},
                record_index=1,
                temp_images_dir=Path(tmp),
                today="20260701",
                field_mapping=self._field_mapping(),
                external_ocr_text="普惠门诊保·如意版(2025)\n意外门诊急诊费用补偿 100000 免赔额100元，给付比例80%",
                ocr_enabled=True,
                ocr_func=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("ocr should not be called")),
                vision_client=FailingVision(),
            )

        self.assertTrue(context.external_ocr_used)
        self.assertFalse(context.vision_triggered)
        self.assertFalse(context.ocr_triggered)
        self.assertEqual(context.records[0]["类型"], "意外门诊急诊费用补偿")
        self.assertEqual(context.records[0]["报销比例"], "80%")

    def test_vision_success_skips_paddle_ocr(self):
        from image_table_pipeline import collect_image_table_context

        class FakeVision:
            model = "fake-vl"

            def is_ready(self):
                return True

            def extract_image_table(self, *_args, **_kwargs):
                return '{"tables_text":"猝死 200000","records":[{"类型":"猝死","补助限额":"200000元"}],"evidence":{}}'

        with tempfile.TemporaryDirectory() as tmp:
            context = collect_image_table_context(
                parsed=self._parsed(image_urls=["a.jpg"]),
                record={},
                record_index=1,
                temp_images_dir=Path(tmp),
                today="20260701",
                field_mapping=self._field_mapping(),
                ocr_enabled=True,
                ocr_func=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("ocr should not be called")),
                vision_client=FakeVision(),
            )

        self.assertTrue(context.vision_triggered)
        self.assertEqual(context.vision_success_count, 1)
        self.assertFalse(context.ocr_triggered)
        self.assertEqual(context.records[0]["类型"], "猝死")

    def test_vision_failure_falls_back_to_paddle_ocr(self):
        from image_ocr import OcrSummary
        from image_table_pipeline import collect_image_table_context

        class FailingVision:
            model = "fake-vl"

            def is_ready(self):
                return True

            def extract_image_table(self, *_args, **_kwargs):
                raise RuntimeError("image input rejected")

        ocr_calls = []

        def fake_ocr(image_urls, temp_dir, record_index, enabled=True, logger=None):
            ocr_calls.append(list(image_urls))
            return OcrSummary(text="意外门诊急诊费用补偿 100000 免赔额100元，给付比例80%", success_count=1, failure_count=0)

        with tempfile.TemporaryDirectory() as tmp:
            context = collect_image_table_context(
                parsed=self._parsed(image_urls=["a.jpg"]),
                record={},
                record_index=1,
                temp_images_dir=Path(tmp),
                today="20260701",
                field_mapping=self._field_mapping(),
                ocr_enabled=True,
                ocr_func=fake_ocr,
                vision_client=FailingVision(),
            )

        self.assertEqual(len(ocr_calls), 1)
        self.assertTrue(context.vision_triggered)
        self.assertTrue(context.ocr_triggered)
        self.assertEqual(context.records[0]["报销比例"], "80%")


if __name__ == "__main__":
    unittest.main()
