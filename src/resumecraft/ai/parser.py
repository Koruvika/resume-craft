"""LlamaCloud PDF resume parser — ported from resumebloom's
`app.components.parser.Parser` (extract v2, agentic tier), minus the
component scaffolding: this raises on failure and the job runner records it."""

import asyncio
import io
from functools import lru_cache

from llama_cloud import LlamaCloud
from llama_cloud.types import ExtractConfigurationParam

from resumecraft.core.config import get_settings
from resumecraft.schemas.parsed_resume import ParsedResume


@lru_cache
def get_parser_client() -> LlamaCloud:
    settings = get_settings()
    if settings.llama_cloud_api_key is None:
        raise ValueError("RC_LLAMA_CLOUD_API_KEY is not set")
    return LlamaCloud(api_key=settings.llama_cloud_api_key.get_secret_value())


async def parse_pdf(file_bytes: bytes, filename: str) -> ParsedResume:
    """Upload a PDF to LlamaCloud and extract it into a ParsedResume."""
    client = get_parser_client()

    file_obj = await asyncio.to_thread(
        client.files.create,
        file=(filename, io.BytesIO(file_bytes), "application/pdf"),
        purpose="extract",
    )
    result = await asyncio.to_thread(
        client.extract.run,
        file_input=file_obj.id,
        configuration=ExtractConfigurationParam(
            data_schema=ParsedResume.model_json_schema(),
            tier="agentic",
            extraction_target="per_doc",
            parse_tier="agentic",
        ),
    )

    data = result.extract_result
    if isinstance(data, list):
        data = data[0] if data else {}
    return ParsedResume.model_validate(data)
