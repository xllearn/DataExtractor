import unittest


class AcceptanceScriptTests(unittest.TestCase):
    def test_acceptance_parser_accepts_image_import_inputs(self):
        from scripts.run_acceptance_all import build_parser

        args = build_parser().parse_args(
            [
                "--image",
                "local/image.jpeg",
                "--manual-excel",
                "local/manual.xlsx",
                "--image-import-table",
                "test_articles",
            ]
        )

        self.assertEqual(args.image, "local/image.jpeg")
        self.assertEqual(args.manual_excel, "local/manual.xlsx")
        self.assertEqual(args.image_import_table, "test_articles")

    def test_image_import_parser_accepts_manual_excel_alias_and_force_flag(self):
        from scripts.run_image_import_test import build_parser

        args = build_parser().parse_args(
            [
                "--result-dir",
                "results",
                "--image",
                "local/image.jpeg",
                "--manual-excel",
                "local/manual.xlsx",
                "--target-table",
                "prod_articles",
            ]
        )

        self.assertEqual(args.manual, "local/manual.xlsx")
        self.assertEqual(args.target_table, "prod_articles")


if __name__ == "__main__":
    unittest.main()
