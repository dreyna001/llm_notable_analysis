import unittest

from onprem_rag.future.prompt_context_builder import (
    ContextSnippet,
    render_context_block,
)


class TestPromptContextBuilder(unittest.TestCase):
    def test_render_context_block_honors_budget(self) -> None:
        snippets = [
            ContextSnippet(source_file="a.docx", section_path="s1", excerpt="first snippet"),
            ContextSnippet(source_file="b.docx", section_path="s2", excerpt="second snippet"),
        ]
        rendered = render_context_block(
            header="SOC_OPERATIONAL_CONTEXT",
            snippets=snippets,
            max_snippets=5,
            budget_chars=90,
        )
        self.assertEqual(rendered.snippet_count, 1)
        self.assertIn("SOC_OPERATIONAL_CONTEXT", rendered.text)
        self.assertIn("a.docx", rendered.text)
        self.assertNotIn("b.docx", rendered.text)

    def test_render_context_block_empty_when_no_snippet_fits(self) -> None:
        snippets = [
            ContextSnippet(
                source_file="a.docx",
                section_path="s1",
                excerpt="x" * 200,
            )
        ]
        rendered = render_context_block(
            header="SOC_OPERATIONAL_CONTEXT",
            snippets=snippets,
            max_snippets=5,
            budget_chars=40,
        )
        self.assertEqual(rendered.text, "")
        self.assertEqual(rendered.snippet_count, 0)


if __name__ == "__main__":
    unittest.main()

