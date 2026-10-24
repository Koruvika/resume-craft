import datetime
import re
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from rendercv.renderer.pdf_png import generate_pdf
from rendercv.renderer.typst import generate_typst
from rendercv.schema.models.design.built_in_design import (
    available_themes,
    built_in_design_adapter,
)
from rendercv.schema.models.locale.locale import Locale
from rendercv.schema.models.rendercv_model import RenderCVModel
from rendercv.schema.models.settings.settings import Settings

from resumecraft.core.exceptions import InvalidRenderOptionError
from resumecraft.schemas.parsed_resume import ParsedResume

# ---------------------------------------------------------------------------
# RenderCV models — mirrors the rendercv-schema.json content (Cv data) types.
# These models represent the YAML structure rendercv expects for PDF generation.
# Design, locale, and render settings are intentionally excluded.
# ---------------------------------------------------------------------------

SocialNetworkName = Literal[
    "LinkedIn",
    "GitHub",
    "GitLab",
    "IMDB",
    "Instagram",
    "ORCID",
    "Mastodon",
    "StackOverflow",
    "ResearchGate",
    "YouTube",
    "Google Scholar",
    "Telegram",
    "WhatsApp",
    "Leetcode",
    "X",
    "Bluesky",
    "Reddit",
]


class RenderCVSocialNetwork(BaseModel):
    model_config = ConfigDict(extra="forbid")

    network: SocialNetworkName = Field(description="Social network platform name")
    username: str = Field(description="Username on the platform")


class RenderCVCustomConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fontawesome_icon: str = Field(description="Font Awesome icon name from fontawesome.com/search")
    placeholder: str = Field(description="Display text for the connection")
    url: str | None = Field(default=None, description="Optional URL for the connection")


class RenderCVExperienceEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    company: str = Field(description="Company name, e.g. Microsoft")
    position: str = Field(description="Job title, e.g. Software Engineer")
    start_date: str | None = Field(
        default=None,
        description="Start date in YYYY-MM-DD, YYYY-MM, or YYYY format",
    )
    end_date: str | None = Field(
        default=None,
        description='End date in YYYY-MM-DD, YYYY-MM, or YYYY format. Use "present" for ongoing.',
    )
    date: str | None = Field(
        default=None,
        description="Single date or arbitrary text like 'Fall 2023'. Prefer start_date/end_date.",
    )
    location: str | None = Field(default=None, description="City, state, country")
    summary: str | None = Field(default=None, description="1-2 sentence overview of the role")
    highlights: list[str] | None = Field(
        default=None,
        description="Bullet points for key achievements, responsibilities, or contributions",
    )


class RenderCVEducationEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    institution: str = Field(description="School, university, or college name")
    area: str = Field(description="Field of study or major, e.g. Computer Science")
    degree: str | None = Field(default=None, description="Degree type, e.g. BS, BA, PhD, MS")
    start_date: str | None = Field(
        default=None,
        description="Start date in YYYY-MM-DD, YYYY-MM, or YYYY format",
    )
    end_date: str | None = Field(
        default=None,
        description='End date in YYYY-MM-DD, YYYY-MM, or YYYY format. Use "present" for ongoing.',
    )
    date: str | None = Field(
        default=None,
        description="Single date or arbitrary text like 'Fall 2023'. Prefer start_date/end_date.",
    )
    location: str | None = Field(default=None, description="City, state, country")
    summary: str | None = Field(default=None, description="1-2 sentence overview")
    highlights: list[str] | None = Field(
        default=None,
        description="Bullet points for key achievements or details",
    )


class RenderCVPublicationEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    title: str = Field(description="Publication title")
    authors: list[str] = Field(
        description="List of author names. Bold yours with **double asterisks**."
    )
    journal: str | None = Field(default=None, description="Journal, conference, or venue name")
    date: str | None = Field(
        default=None,
        description="Publication date in YYYY-MM-DD, YYYY-MM, YYYY, or arbitrary text",
    )
    summary: str | None = Field(default=None, description="Abstract or summary")
    doi: str | None = Field(
        default=None, description="Digital Object Identifier, e.g. 10.48550/arXiv.2310.03138"
    )
    url: str | None = Field(default=None, description="URL to the publication")


class RenderCVNormalEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(description="Entry name, e.g. project, award, or event title")
    start_date: str | None = Field(
        default=None,
        description="Start date in YYYY-MM-DD, YYYY-MM, or YYYY format",
    )
    end_date: str | None = Field(
        default=None,
        description='End date in YYYY-MM-DD, YYYY-MM, or YYYY format. Use "present" for ongoing.',
    )
    date: str | None = Field(
        default=None,
        description="Single date or arbitrary text like 'Fall 2023'. Prefer start_date/end_date.",
    )
    location: str | None = Field(default=None, description="City, state, country")
    summary: str | None = Field(default=None, description="1-2 sentence overview")
    highlights: list[str] | None = Field(
        default=None,
        description="Bullet points for key achievements, responsibilities, or contributions",
    )


class RenderCVOneLineEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    label: str = Field(description="Label text, e.g. 'Languages', 'Citizenship'")
    details: str = Field(description="Details text, e.g. 'English (native), Spanish (fluent)'")


class RenderCVBulletEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    bullet: str = Field(description="A single bullet point, e.g. 'Python, JavaScript, C++'")


class RenderCVNumberedEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    number: str = Field(description="Numbered entry text, e.g. 'First publication about XYZ'")


class RenderCVReversedNumberedEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    reversed_number: str = Field(
        description="Reverse-numbered entry text, e.g. 'Latest research paper'"
    )


RenderCVSectionEntry = (
    str
    | RenderCVOneLineEntry
    | RenderCVNormalEntry
    | RenderCVExperienceEntry
    | RenderCVEducationEntry
    | RenderCVPublicationEntry
    | RenderCVBulletEntry
    | RenderCVNumberedEntry
    | RenderCVReversedNumberedEntry
)


class RenderCVCv(BaseModel):
    """The `cv` section of a RenderCV YAML file.

    This is the data-level model matching rendercv-schema.json's `Cv` definition.
    Sections are freeform — keys are section titles (e.g. "Experience",
    "Education") and values are lists of entry objects whose type is
    auto-detected by their fields. The model accepts arbitrary
    section names via additionalProperties.

    For PDF generation, we convert from ParsedResume → RenderCVCv.
    """

    model_config = ConfigDict(extra="allow")

    name: str | None = Field(default=None, description="Full name displayed on the CV")
    headline: str | None = Field(
        default=None, description="Professional headline, e.g. Software Engineer"
    )
    location: str | None = Field(default=None, description="Location, e.g. 'New York, NY'")
    email: str | list[str] | None = Field(
        default=None, description="Email address(es). Single string or list."
    )
    phone: str | list[str] | None = Field(
        default=None,
        description="Phone number(s) with country code. Single string or list.",
    )
    website: str | list[str] | None = Field(
        default=None, description="Website URL(s). Single string or list."
    )
    photo: str | None = Field(default=None, description="Photo file path (relative) or URL")
    social_networks: list[RenderCVSocialNetwork] | None = Field(default=None)
    custom_connections: list[RenderCVCustomConnection] | None = Field(default=None)
    sections: dict[str, list[RenderCVSectionEntry]] | None = Field(
        default=None,
        description="Section title → list of entries. Entry types auto-detected by fields.",
    )


def parsed_resume_to_rendercv(resume: ParsedResume) -> RenderCVCv:
    """Convert a ParsedResume to a RenderCVCv for PDF generation.

    Maps fields by name, restructures flat contact info into RenderCV's
    header format, and organizes typed section lists into RenderCV's
    freeform sections dict.
    """

    emails = (
        resume.contact_info.emails
        if resume.contact_info.emails
        else ([e.strip() for e in resume.contact_info.email.split(",") if e.strip()] or None)
    )
    raw_phones = (
        resume.contact_info.phones
        if resume.contact_info.phones
        else ([p.strip() for p in resume.contact_info.phone.split(",") if p.strip()] or None)
    )
    phones = None
    if raw_phones:
        normalized = [normalize_phone(p) for p in raw_phones]
        phones = [p for p in normalized if p is not None] or None
    websites: list[str] | None = None
    ws = resume.contact_info.website or resume.contact_info.portfolio_url
    if ws:
        websites = [normalize_website_url(ws)]

    cv_social_networks: list[RenderCVSocialNetwork] | None = None
    if resume.profiles:
        cv_social_networks = []
        for p in resume.profiles:
            if not p.network:
                continue
            net = try_normalize_network_name(p.network)
            if net is not None:
                cv_social_networks.append(
                    RenderCVSocialNetwork(
                        network=net,
                        username=p.username or p.url.rsplit("/", 1)[-1],
                    )
                )
            elif p.url:
                if websites is None:
                    websites = []
                w = normalize_website_url(p.url)
                if w and w not in websites:
                    websites.append(w)
        if not cv_social_networks:
            cv_social_networks = None
    linkedin_in_profiles = any(
        try_normalize_network_name(p.network) == "LinkedIn"
        for p in (resume.profiles or [])
        if p.network
    )
    if resume.contact_info.linkedin_url and not linkedin_in_profiles:
        username = resume.contact_info.linkedin_url.rstrip("/").rsplit("/", 1)[-1]
        if cv_social_networks is None:
            cv_social_networks = []
        cv_social_networks.append(RenderCVSocialNetwork(network="LinkedIn", username=username))

    experience_entries: list[RenderCVSectionEntry] = [
        RenderCVExperienceEntry(
            company=e.company,
            position=e.job_title,
            start_date=normalize_rendercv_date(e.start_date),
            end_date=make_end_date(e.end_date, e.is_current),
            location=e.location or None,
            summary=e.summary or None,
            highlights=e.achievements if e.achievements else None,
        )
        for e in resume.experience
    ]

    education_entries: list[RenderCVSectionEntry] = [
        RenderCVEducationEntry(
            institution=e.institution,
            area=e.area,
            degree=e.degree or None,
            start_date=normalize_rendercv_date(e.start_date),
            end_date=normalize_rendercv_date(e.graduation_date),
            date=normalize_rendercv_date(e.graduation_date),
            location=e.location or None,
            summary=e.description or None,
            highlights=e.highlights
            if e.highlights
            else (e.honors.split(", ") if e.honors else None),
        )
        for e in resume.education
    ]

    skills_entries: list[RenderCVSectionEntry] | None = None
    if resume.skills.groups:
        skills_entries = [
            RenderCVBulletEntry(bullet=f"{g.category}: {', '.join(g.skills)}")
            if g.category
            else RenderCVBulletEntry(bullet=", ".join(g.skills))
            for g in resume.skills.groups
        ]

    project_entries: list[RenderCVSectionEntry] = [
        RenderCVNormalEntry(
            name=p.name,
            summary=p.description or None,
            highlights=_project_highlights(p),
        )
        for p in resume.projects
    ]

    language_entries: list[RenderCVSectionEntry] | None = None
    if resume.languages:
        language_entries = [
            RenderCVOneLineEntry(
                label=lang.language,
                details=lang.fluency
                if lang.fluency
                else f"Level {lang.level}"
                if lang.level
                else "",
            )
            for lang in resume.languages
        ]

    award_entries: list[RenderCVSectionEntry] = [
        RenderCVNormalEntry(
            name=a.title,
            date=normalize_rendercv_date(a.date),
            summary=a.description or None,
        )
        for a in resume.awards
    ]

    cert_entries: list[RenderCVSectionEntry] = [
        RenderCVNormalEntry(
            name=c.title,
            date=normalize_rendercv_date(c.date),
            summary=c.description or None,
        )
        for c in resume.certifications
    ]

    volunteer_entries: list[RenderCVSectionEntry] = [
        RenderCVNormalEntry(
            name=v.organization,
            location=v.location or None,
            summary=v.description or None,
        )
        for v in resume.volunteer
    ]

    publication_entries: list[RenderCVSectionEntry] = [
        RenderCVPublicationEntry(
            title=p.title,
            authors=p.authors if p.authors else [],
            journal=p.journal or p.publisher or None,
            date=p.date or None,
            doi=p.doi or None,
            summary=p.description or None,
            url=p.website or None,
        )
        for p in resume.publications
    ]

    interest_bullets: list[RenderCVSectionEntry] | None = None
    if resume.interests:
        interest_bullets = []
        for i in resume.interests:
            if i.keywords:
                interest_bullets.append(
                    RenderCVBulletEntry(bullet=f"{i.name}: {', '.join(i.keywords)}")
                )
            else:
                interest_bullets.append(RenderCVBulletEntry(bullet=i.name))

    sections: dict[str, list[RenderCVSectionEntry]] = {}
    if resume.summary:
        sections["Summary"] = [resume.summary]
    if experience_entries:
        sections["Experience"] = experience_entries
    if education_entries:
        sections["Education"] = education_entries
    if skills_entries:
        sections["Skills"] = skills_entries
    if project_entries:
        sections["Projects"] = project_entries
    if language_entries:
        sections["Languages"] = language_entries
    if award_entries:
        sections["Awards"] = award_entries
    if cert_entries:
        sections["Certifications"] = cert_entries
    if volunteer_entries:
        sections["Volunteer"] = volunteer_entries
    if publication_entries:
        sections["Publications"] = publication_entries
    if interest_bullets:
        sections["Interests"] = interest_bullets

    return RenderCVCv(
        name=resume.contact_info.full_name or None,
        headline=resume.contact_info.headline or None,
        location=resume.contact_info.location or None,
        photo=resume.contact_info.photo_url or None,
        email=emails,
        phone=phones,
        website=websites,
        social_networks=cv_social_networks,
        sections=sections or None,
    )


def _project_highlights(p) -> list[str] | None:
    items: list[str] = []
    items.extend(p.achievements)
    if p.technologies:
        items.append(f"**Technologies**: {', '.join(p.technologies)}")
    return items or None


def normalize_rendercv_date(date_str: str | None) -> str | None:
    if not date_str:
        return None
    m = re.match(r"^(\d{1,2})/(\d{4})$", date_str.strip())
    if m:
        return f"{m.group(2)}-{int(m.group(1)):02d}"
    m = re.match(r"^([A-Za-z]+)\s+(\d{4})$", date_str.strip())
    if m:
        try:
            month = datetime.datetime.strptime(m.group(1)[:3].title(), "%b").month
            return f"{m.group(2)}-{month:02d}"
        except ValueError:
            return date_str
    return date_str


def normalize_website_url(url: str) -> str:
    stripped = url.strip()
    if not stripped:
        return stripped
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", stripped):
        return f"https://{stripped}"
    return stripped


def normalize_phone(phone: str) -> str | None:
    stripped = phone.strip()
    if not stripped:
        return None
    if not stripped.startswith("+"):
        return None
    return stripped


def make_end_date(end_date: str, is_current: bool) -> str | None:
    """Convert ParsedResume end_date/is_current to RenderCV end_date format.

    RenderCV uses the literal string "present" for ongoing positions.
    """
    if is_current:
        return "present"
    return end_date or None


def normalize_network_name(network: str) -> SocialNetworkName:
    """Map a free-form network name to RenderCV's SocialNetworkName enum.

    Tries case-insensitive prefix matching against the known networks.
    Falls back to the closest match or raises ValueError.
    """
    if not network:
        raise ValueError("Network name cannot be empty")
    normalized = network.strip().lower().replace(" ", "").replace("-", "")
    mapping: dict[str, SocialNetworkName] = {
        "linkedin": "LinkedIn",
        "github": "GitHub",
        "gitlab": "GitLab",
        "imdb": "IMDB",
        "instagram": "Instagram",
        "orcid": "ORCID",
        "mastodon": "Mastodon",
        "stackoverflow": "StackOverflow",
        "stack_overflow": "StackOverflow",
        "researchgate": "ResearchGate",
        "research_gate": "ResearchGate",
        "youtube": "YouTube",
        "googlescholar": "Google Scholar",
        "google_scholar": "Google Scholar",
        "telegram": "Telegram",
        "whatsapp": "WhatsApp",
        "leetcode": "Leetcode",
        "x": "X",
        "twitter": "X",
        "bluesky": "Bluesky",
        "reddit": "Reddit",
    }
    if normalized in mapping:
        return mapping[normalized]
    for key, value in mapping.items():
        if normalized.startswith(key):
            return value
    raise ValueError(f"Unknown social network: {network!r}")


def try_normalize_network_name(network: str) -> SocialNetworkName | None:
    """Non-raising variant of normalize_network_name.

    Returns None for networks RenderCV doesn't model as social networks
    (e.g. "Website", "Portfolio") — callers route those to the CV header's
    website field instead of social_networks.
    """
    try:
        return normalize_network_name(network)
    except ValueError:
        return None


VALID_THEMES = set(available_themes)

LOCALE_ADAPTER = TypeAdapter(Locale)
VALID_LOCALES = [
    "arabic",
    "danish",
    "dutch",
    "english",
    "french",
    "german",
    "hebrew",
    "hindi",
    "hungarian",
    "indonesian",
    "italian",
    "japanese",
    "korean",
    "mandarin_chinese",
    "norwegian_bokmål",
    "norwegian_nynorsk",
    "persian",
    "portuguese",
    "russian",
    "spanish",
    "turkish",
    "vietnamese",
]

DEFAULT_THEME = "classic"
DEFAULT_LOCALE = "english"


class RenderOptions(BaseModel):
    """Validated theme/locale picked for one render — resumecraft has no
    stored per-user render settings, so callers pass these per request."""

    model_config = ConfigDict(extra="forbid")

    theme: str = Field(default=DEFAULT_THEME, description="Resume render theme name.")
    locale: str = Field(
        default=DEFAULT_LOCALE, description="Render locale for date/section labels."
    )


def validate_render_options(theme: str | None, locale: str | None) -> RenderOptions:
    """Validate free-form theme/locale strings into a RenderOptions.

    Raises InvalidRenderOptionError (422 upstream) listing what's supported,
    so clients can self-correct without another round trip.
    """
    theme = theme or DEFAULT_THEME
    locale = locale or DEFAULT_LOCALE
    if theme not in VALID_THEMES:
        raise InvalidRenderOptionError(
            f"Unknown theme {theme!r}",
            details={"option": "theme", "value": theme, "supported": sorted(VALID_THEMES)},
        )
    if locale not in VALID_LOCALES:
        raise InvalidRenderOptionError(
            f"Unknown locale {locale!r}",
            details={"option": "locale", "value": locale, "supported": VALID_LOCALES},
        )
    return RenderOptions(theme=theme, locale=locale)


def build_rendercv_model(
    cv,
    render_options: RenderOptions,
) -> RenderCVModel:
    cv_dict = cv.model_dump(mode="python", exclude_none=True)
    design_dict = {"theme": render_options.theme, "page": {"show_top_note": False}}
    design = built_in_design_adapter.validate_python(design_dict)

    locale_dict = {"language": render_options.locale}
    locale = LOCALE_ADAPTER.validate_python(locale_dict)

    settings = Settings()

    model = RenderCVModel(
        cv=cv_dict,
        design=design,
        locale=locale,
        settings=settings,
    )
    return model


def generate_pdf_bytes(
    rendercv_model: RenderCVModel,
    filename: str,
) -> tuple[bytes, str]:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        input_path = tmpdir_path / "input.yaml"
        input_path.write_text("# placeholder", encoding="utf-8")

        rendercv_model._input_file_path = input_path

        typst_path = tmpdir_path / "output.typ"
        pdf_path = tmpdir_path / "output.pdf"

        rendercv_model.settings.render_command.typst_path = typst_path
        rendercv_model.settings.render_command.pdf_path = pdf_path
        rendercv_model.settings.render_command.output_folder = tmpdir_path
        rendercv_model.settings.render_command.dont_generate_markdown = True
        rendercv_model.settings.render_command.dont_generate_html = True
        rendercv_model.settings.render_command.dont_generate_png = True

        typst_result = generate_typst(rendercv_model)
        pdf_result = generate_pdf(rendercv_model, typst_result)

        pdf_bytes = pdf_result.read_bytes()

    return pdf_bytes, filename
