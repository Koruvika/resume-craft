"""ParsedResume → PDF rendering, via the rendercv/typst pipeline.

Ported from resumebloom's `app.components.render` so both projects render the
same canonical `ParsedResume` identically. This package is pure conversion +
generation: no DB, no services, no framework — anything that needs a PDF calls
`generate_pdf_bytes` with a `RenderCVModel`.
"""

from resumecraft.rendering.render import (
    DEFAULT_LOCALE,
    DEFAULT_THEME,
    RenderCVCv,
    RenderOptions,
    build_rendercv_model,
    generate_pdf_bytes,
    parsed_resume_to_rendercv,
    validate_render_options,
)

__all__ = [
    "DEFAULT_LOCALE",
    "DEFAULT_THEME",
    "RenderCVCv",
    "RenderOptions",
    "build_rendercv_model",
    "generate_pdf_bytes",
    "parsed_resume_to_rendercv",
    "validate_render_options",
]
