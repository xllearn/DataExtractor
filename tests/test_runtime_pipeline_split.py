import unittest


class RuntimePipelineSplitTests(unittest.TestCase):
    def test_runtime_exports_existing_runtime_helpers(self):
        import runtime

        self.assertTrue(callable(runtime.resolve_runtime_flags))
        self.assertTrue(callable(runtime.resolve_effective_limit))
        self.assertTrue(callable(runtime.validate_keyword_supported))
        self.assertTrue(callable(runtime.validate_strict_runtime_config))

    def test_pipeline_exports_single_record_helpers(self):
        import pipeline

        self.assertTrue(callable(pipeline.extract_record_rows))
        self.assertTrue(callable(pipeline.extract_once_detail))
        self.assertTrue(callable(pipeline.choose_final_attempt))


if __name__ == "__main__":
    unittest.main()
