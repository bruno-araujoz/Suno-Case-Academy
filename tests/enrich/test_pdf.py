from scraper.enrich.pdf import pdf_to_text
from tests.helpers import FIXTURES


def test_pdf_to_text_extracts_readable_paragraphs():
    text = pdf_to_text((FIXTURES / "cvm_ipe/fato_relevante.pdf").read_bytes())
    assert len(text) > 500
    assert "FATO RELEVANTE" in text.upper()
    assert "\n\n" in text  # paragraphs preserved
