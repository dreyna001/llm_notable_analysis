import unittest

from onprem_rag_notable_analysis.future.embedding_text import format_embedding_query_text


class TestEmbeddingText(unittest.TestCase):
    def test_mixedbread_query_gets_retrieval_prefix(self) -> None:
        """Mixedbread query embeddings should use the documented retrieval prompt."""
        result = format_embedding_query_text(
            model_name="mixedbread-ai/mxbai-embed-large-v1",
            query_text="suspicious powershell",
        )
        self.assertTrue(result.startswith("Represent this sentence for searching"))
        self.assertIn("suspicious powershell", result)

    def test_non_mixedbread_query_is_unchanged(self) -> None:
        """Other models should keep the raw query text."""
        result = format_embedding_query_text(
            model_name="custom/embedder",
            query_text="suspicious powershell",
        )
        self.assertEqual(result, "suspicious powershell")


if __name__ == "__main__":
    unittest.main()
