"""Structured contracts of the generation graph (also the JSON schemas sent to the LLM).

Limits (max_length, list sizes) are validated locally by Pydantic; providers' strict mode does not
support them, so the router repairs once when they are violated (see llm/schema.py).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Format = Literal["artigo", "carrossel", "roteiro"]
Level = Literal["iniciante", "intermediario", "avancado"]
FORMATS: tuple[Format, ...] = ("artigo", "carrossel", "roteiro")
LEVELS: tuple[Level, ...] = ("iniciante", "intermediario", "avancado")


# ------------------------------------------------------------------ anchors (ground truth)


class Fact(BaseModel):
    id: str = Field(description="F1, F2, ...")
    afirmacao: str = Field(description="o fato, em uma frase objetiva")
    numeros: list[str] = Field(description="números/percentuais exatamente como na fonte")
    doc_id: str = Field(description="id do documento de onde o fato saiu (ex.: D1)")
    citacao: str = Field(description="trecho literal da fonte que sustenta o fato")
    central: bool = Field(description="true se é um dos fatos centrais do evento")


class Anchors(BaseModel):
    evento: str = Field(description="o acontecimento em uma frase")
    contexto: str = Field(description="por que importa / pano de fundo, 1-2 frases")
    fatos: list[Fact] = Field(min_length=2, max_length=12)
    implicacoes: list[str] = Field(
        max_length=5, description="consequências citadas ou diretas da fonte"
    )


# ------------------------------------------------------------------ formats


class Section(BaseModel):
    subtitulo: str = Field(max_length=90)
    texto: str


class Article(BaseModel):
    titulo: str = Field(max_length=110)
    lead: str = Field(max_length=400)
    secoes: list[Section] = Field(min_length=3, max_length=5)
    conclusao: str


class Slide(BaseModel):
    papel: Literal["gancho", "corpo", "conclusao"]
    titulo: str = Field(max_length=60)
    texto: str = Field(max_length=280)


class Carousel(BaseModel):
    slides: list[Slide] = Field(min_length=6, max_length=10)
    legenda: str = Field(max_length=600)
    hashtags: list[str] = Field(max_length=5)


class ScriptBlock(BaseModel):
    inicio_s: int = Field(ge=0, le=60)
    fim_s: int = Field(ge=1, le=60)
    gancho_visual: str = Field(max_length=160, description="o que aparece na tela")
    fala: str = Field(description="texto falado neste bloco")


class Script(BaseModel):
    titulo: str = Field(max_length=90)
    blocos: list[ScriptBlock] = Field(min_length=3, max_length=8)


SCHEMAS: dict[Format, type[BaseModel]] = {
    "artigo": Article,
    "carrossel": Carousel,
    "roteiro": Script,
}


def reader_text(fmt: Format, content: BaseModel) -> str:
    """The text a reader/listener actually gets — what readability and jargon are measured on.

    Excludes structure (timestamps, hashtags) so they do not distort the metrics.
    """
    if fmt == "artigo":
        assert isinstance(content, Article)
        parts = [content.titulo, content.lead]
        for s in content.secoes:
            parts += [s.subtitulo, s.texto]
        parts.append(content.conclusao)
    elif fmt == "carrossel":
        assert isinstance(content, Carousel)
        parts = [f"{s.titulo}. {s.texto}" for s in content.slides] + [content.legenda]
    else:
        assert isinstance(content, Script)
        parts = [b.fala for b in content.blocos]
    return "\n\n".join(p.strip() for p in parts if p and p.strip())
