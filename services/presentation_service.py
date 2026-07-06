from __future__ import annotations

import base64
import asyncio
from io import BytesIO
import json
import re
import unicodedata

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor
from openai import AsyncOpenAI
from openai import APIConnectionError, APIStatusError, RateLimitError


class PresentationService:
    def __init__(
        self,
        api_key: str,
        text_model: str,
        image_model: str = "gpt-image-1",
        image_concurrency: int = 4,
        image_quality: str = "low",
    ):
        self.client = AsyncOpenAI(api_key=api_key) if api_key else None
        self.text_model = text_model
        self.image_model = image_model
        self.image_concurrency = max(1, min(image_concurrency, 6))
        self.image_quality = image_quality

    async def create_plan(self, title: str, answer: str) -> dict:
        if not self.client:
            raise RuntimeError("A chave OPENAI_API_KEY ainda não foi configurada no arquivo .env.")
        response = await self.client.responses.create(
            model=self.text_model,
            instructions=(
                "Organize exclusivamente o conteúdo fornecido em 4 a 8 tópicos para uma pregação ou palestra. "
                "Não acrescente fatos, citações ou referências externas. Cada tópico deve ter título curto, "
                "síntese de até 45 palavras e 2 a 4 pontos de desenvolvimento. Crie também um título de capa "
                "marcante, coerente e com no máximo 7 palavras, e uma frase final de até 24 palavras que resuma "
                "a mensagem central. Responda somente em JSON válido."
            ),
            input=f"TÍTULO: {title}\n\nCONTEÚDO: {answer}",
            text={"format": {"type": "json_schema", "name": "roteiro", "strict": True, "schema": {
                "type": "object", "properties": {
                "titulo_curto": {"type": "string"},
                "frase_final": {"type": "string"},
                "topicos": {"type": "array", "minItems": 4, "maxItems": 8,
                "items": {"type": "object", "properties": {
                    "titulo": {"type": "string"}, "sintese": {"type": "string"},
                    "pontos": {"type": "array", "minItems": 2, "maxItems": 4, "items": {"type": "string"}}
                }, "required": ["titulo", "sintese", "pontos"], "additionalProperties": False}}},
                "required": ["titulo_curto", "frase_final", "topicos"], "additionalProperties": False}}},
            max_output_tokens=1800,
        )
        return json.loads(response.output_text)

    async def create_outline(self, title: str, answer: str) -> list[dict]:
        return (await self.create_plan(title, answer))["topicos"]

    def create_docx(self, title: str, topics: list[dict]) -> bytes:
        doc = Document()
        section = doc.sections[0]
        section.top_margin = section.bottom_margin = Inches(0.8)
        section.left_margin = section.right_margin = Inches(0.9)
        doc.styles["Normal"].font.name = "Aptos"
        doc.styles["Normal"].font.size = Pt(11)
        doc.styles["Heading 1"].font.name = "Aptos Display"
        doc.styles["Heading 1"].font.size = Pt(16)
        doc.styles["Heading 1"].font.color.rgb = RGBColor(91, 55, 28)
        kicker = doc.add_paragraph()
        kicker.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = kicker.add_run("MAGISTERIA · ROTEIRO PARA PREGAÇÃO OU PALESTRA")
        run.bold = True
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor(174, 124, 55)
        heading = doc.add_paragraph()
        heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        title_run = heading.add_run(title)
        title_run.bold = True
        title_run.font.name = "Aptos Display"
        title_run.font.size = Pt(25)
        title_run.font.color.rgb = RGBColor(54, 38, 29)
        doc.add_paragraph("Tópicos organizados a partir da pesquisa realizada no MAGISTERIA.").alignment = WD_ALIGN_PARAGRAPH.CENTER
        for number, topic in enumerate(topics, 1):
            doc.add_heading(f"{number}. {topic['titulo']}", level=1)
            doc.add_paragraph(topic["sintese"])
            for point in topic["pontos"]:
                doc.add_paragraph(point, style="List Bullet")
        footer = section.footer.paragraphs[0]
        footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
        footer.add_run("MAGISTERIA · Conteúdo fundamentado na pesquisa selecionada").font.size = Pt(8)
        output = BytesIO()
        doc.save(output)
        return output.getvalue()

    async def create_pptx(
        self,
        title: str,
        topics: list[dict],
        short_title: str | None = None,
        closing_phrase: str | None = None,
    ) -> bytes:
        from pptx import Presentation
        from pptx.util import Inches as PptInches

        short_title = short_title or title
        closing_phrase = closing_phrase or "A mensagem acolhida com fé transforma a vida e renova a esperança."
        visual_brief = [
            {"titulo": short_title, "sintese": title, "visual_role": "cover"},
            *topics,
            {"titulo": "Encerramento", "sintese": closing_phrase, "visual_role": "closing"},
        ]
        images = await self._generate_images(title, visual_brief)
        prs = Presentation()
        prs.slide_width, prs.slide_height = PptInches(13.333), PptInches(7.5)
        self._add_title_slide(prs, short_title, images[0])
        for number, (topic, image) in enumerate(zip(topics, images[1:-1]), 1):
            self._add_topic_slide(prs, number, topic, image)
        self._add_closing_slide(prs, closing_phrase, images[-1])
        output = BytesIO()
        prs.save(output)
        return output.getvalue()

    async def _generate_images(self, title: str, topics: list[dict]) -> list[BytesIO]:
        semaphore = asyncio.Semaphore(self.image_concurrency)

        async def generate(topic: dict) -> BytesIO:
            async with semaphore:
                return await self._generate_image_with_retry(title, topic)

        results = await asyncio.gather(*(generate(topic) for topic in topics), return_exceptions=True)
        # Um limite momentâneo em uma imagem não deve descartar todas as demais.
        for index, result in enumerate(results):
            if isinstance(result, Exception):
                await asyncio.sleep(1)
                results[index] = await self._generate_image_with_retry(title, topics[index], attempts=3)
        return list(results)

    async def _generate_image_with_retry(self, title: str, topic: dict, attempts: int = 2) -> BytesIO:
        for attempt in range(attempts):
            try:
                return await self._generate_image(title, topic)
            except (RateLimitError, APIConnectionError) as exc:
                if attempt + 1 == attempts:
                    raise RuntimeError(
                        "O serviço de imagens está temporariamente ocupado. Aguarde alguns instantes e tente novamente."
                    ) from exc
                await asyncio.sleep(1.5 * (attempt + 1))
            except APIStatusError as exc:
                if exc.status_code >= 500 and attempt + 1 < attempts:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                raise
        raise RuntimeError("Não foi possível concluir a geração das imagens.")

    async def _generate_image(self, title: str, topic: dict) -> BytesIO:
        role = topic.get("visual_role", "topic")
        direction = {
            "cover": (
                "Imagem de capa impactante, majestosa e emocional, com forte profundidade, luz dramática e um "
                "ponto focal simbólico. Reserve área escura e limpa no centro para sobrepor um título."
            ),
            "closing": (
                "Imagem final luminosa, serena e esperançosa, com atmosfera de comunhão, gratidão e bênção. "
                "Reserve espaço central limpo para uma frase de encerramento."
            ),
            "topic": "Imagem narrativa coerente com o tópico, com foco visual claro e composição elegante.",
        }[role]
        prompt = (
            "Ilustração editorial cinematográfica, reverente e acolhedora, sem texto, letras ou logotipos, "
            "para apresentação católica contemporânea. Evite retratar Deus literalmente. "
            f"{direction} Tema geral: {title}. Tópico: {topic['titulo']}. Ideia: {topic['sintese']}"
        )
        result = await self.client.images.generate(
            model=self.image_model,
            prompt=prompt,
            size="1024x1024",
            quality=self.image_quality,
            output_format="jpeg",
            output_compression=72,
        )
        return BytesIO(base64.b64decode(result.data[0].b64_json))

    @staticmethod
    def _add_title_slide(prs, title: str, image: BytesIO) -> None:
        from pptx.dml.color import RGBColor as PptRGBColor
        from pptx.enum.text import PP_ALIGN
        from pptx.util import Inches as PptInches, Pt as PptPt

        slide = prs.slides.add_slide(prs.slide_layouts[6])
        slide.shapes.add_picture(image, 0, 0, width=prs.slide_width, height=prs.slide_height)
        frame = slide.shapes.add_textbox(PptInches(1.25), PptInches(2.05), PptInches(10.83), PptInches(3.5)).text_frame
        p = frame.paragraphs[0]
        p.text, p.alignment = title, PP_ALIGN.CENTER
        p.font.name, p.font.size, p.font.bold = "Aptos Display", PptPt(50), True
        p.font.color.rgb = PptRGBColor(255, 248, 235)
        sub = frame.add_paragraph()
        sub.text, sub.alignment = "Gerado com curadoria via MagisterIA", PP_ALIGN.CENTER
        sub.space_before = PptPt(22)
        sub.font.size, sub.font.color.rgb = PptPt(18), PptRGBColor(255, 238, 207)

    @staticmethod
    def _add_topic_slide(prs, number: int, topic: dict, image: BytesIO) -> None:
        from pptx.dml.color import RGBColor as PptRGBColor
        from pptx.util import Inches as PptInches, Pt as PptPt

        slide = prs.slides.add_slide(prs.slide_layouts[6])
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = PptRGBColor(250, 246, 238)
        slide.shapes.add_picture(image, PptInches(6.55), 0, width=PptInches(6.783), height=PptInches(7.5))
        frame = slide.shapes.add_textbox(PptInches(0.7), PptInches(0.55), PptInches(5.35), PptInches(6.3)).text_frame
        frame.word_wrap = True
        p = frame.paragraphs[0]
        p.text = f"{number:02d}  {topic['titulo']}"
        p.font.name, p.font.size, p.font.bold = "Aptos Display", PptPt(35), True
        p.font.color.rgb = PptRGBColor(70, 44, 30)
        lead = frame.add_paragraph()
        lead.text, lead.space_before, lead.space_after = topic["sintese"], PptPt(18), PptPt(14)
        lead.font.size, lead.font.color.rgb = PptPt(20), PptRGBColor(91, 71, 58)
        for point in topic["pontos"]:
            bullet = frame.add_paragraph()
            bullet.text, bullet.font.size, bullet.space_after = f"• {point}", PptPt(17), PptPt(8)
            bullet.font.color.rgb = PptRGBColor(54, 45, 40)

    @staticmethod
    def _add_closing_slide(prs, phrase: str, image: BytesIO) -> None:
        from pptx.dml.color import RGBColor as PptRGBColor
        from pptx.enum.text import PP_ALIGN
        from pptx.util import Inches as PptInches, Pt as PptPt

        slide = prs.slides.add_slide(prs.slide_layouts[6])
        slide.shapes.add_picture(image, 0, 0, width=prs.slide_width, height=prs.slide_height)
        frame = slide.shapes.add_textbox(PptInches(1.3), PptInches(1.45), PptInches(10.73), PptInches(4.9)).text_frame
        frame.word_wrap = True
        p = frame.paragraphs[0]
        p.text, p.alignment = phrase, PP_ALIGN.CENTER
        p.font.name, p.font.size, p.font.bold = "Aptos Display", PptPt(34), True
        p.font.color.rgb = PptRGBColor(255, 250, 239)
        thanks = frame.add_paragraph()
        thanks.text, thanks.alignment = "Obrigado pela atenção!", PP_ALIGN.CENTER
        thanks.space_before = PptPt(28)
        thanks.font.size, thanks.font.bold = PptPt(24), True
        thanks.font.color.rgb = PptRGBColor(239, 202, 132)
        blessing = frame.add_paragraph()
        blessing.text, blessing.alignment = "Que a bênção de Deus esteja com todos!", PP_ALIGN.CENTER
        blessing.space_before = PptPt(12)
        blessing.font.size = PptPt(22)
        blessing.font.color.rgb = PptRGBColor(255, 248, 235)


def safe_filename(title: str, suffix: str) -> str:
    value = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()[:60] or "magisteria"
    return f"{slug}-{suffix}"
