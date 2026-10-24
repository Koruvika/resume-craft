"""Unit tests for the ParsedResume → RenderCVCv conversion (no typst runs)."""

import pytest

from resumecraft.core.exceptions import InvalidRenderOptionError
from resumecraft.rendering import (
    parsed_resume_to_rendercv,
    validate_render_options,
)
from resumecraft.rendering.render import (
    make_end_date,
    normalize_network_name,
    normalize_phone,
    normalize_rendercv_date,
    normalize_website_url,
    try_normalize_network_name,
)
from resumecraft.schemas.parsed_resume import ParsedResume


def _sample_resume() -> ParsedResume:
    return ParsedResume.model_validate(
        {
            "contact_info": {
                "full_name": "Jane Doe",
                "headline": "Staff Engineer",
                "location": "New York, NY",
                "email": "jane@x.com, jane2@x.com",
                "phone": "+1 555 0100",
                "portfolio_url": "janedoe.dev",
                "linkedin_url": "https://linkedin.com/in/janedoe",
            },
            "summary": "Backend engineer.",
            "experience": [
                {
                    "job_title": "Senior Engineer",
                    "company": "Acme",
                    "location": "Remote",
                    "start_date": "01/2023",
                    "end_date": "",
                    "is_current": True,
                    "summary": "Led the platform team.",
                    "achievements": ["Shipped v2"],
                },
                {
                    "job_title": "Engineer",
                    "company": "Globex",
                    "start_date": "Jun 2020",
                    "end_date": "12/2022",
                    "is_current": False,
                },
            ],
            "education": [
                {
                    "degree": "BS",
                    "institution": "MIT",
                    "area": "Computer Science",
                    "start_date": "2014",
                    "graduation_date": "05/2018",
                    "honors": "Summa Cum Laude, Dean's List",
                }
            ],
            "skills": {"groups": [{"category": "Languages", "skills": ["python", "go"]}]},
            "projects": [
                {
                    "name": "Sidecar",
                    "description": "A proxy.",
                    "technologies": ["rust"],
                    "achievements": ["1k stars"],
                }
            ],
            "languages": [
                {"language": "English", "fluency": "Native", "level": 5},
                {"language": "German", "fluency": "", "level": 2},
            ],
            "profiles": [
                {"network": "GitHub", "username": "janedoe", "url": "https://github.com/janedoe"},
                {"network": "Website", "url": "https://blog.janedoe.dev"},
            ],
            "interests": [{"name": "Climbing", "keywords": ["boulder"]}],
        }
    )


def test_conversion_maps_header_fields() -> None:
    cv = parsed_resume_to_rendercv(_sample_resume())

    assert cv.name == "Jane Doe"
    assert cv.headline == "Staff Engineer"
    assert cv.location == "New York, NY"
    assert cv.email == ["jane@x.com", "jane2@x.com"]
    assert cv.phone == ["+1 555 0100"]
    assert cv.website == ["https://janedoe.dev", "https://blog.janedoe.dev"]


def test_conversion_maps_social_networks() -> None:
    cv = parsed_resume_to_rendercv(_sample_resume())

    assert cv.social_networks is not None
    networks = [(s.network, s.username) for s in cv.social_networks]
    assert ("GitHub", "janedoe") in networks
    # LinkedIn derived from contact_info when not present in profiles.
    assert ("LinkedIn", "janedoe") in networks
    # Unknown "Website" profile is routed to header websites, not socials.
    assert all(s.network != "Website" for s in cv.social_networks)


def test_conversion_maps_sections() -> None:
    cv = parsed_resume_to_rendercv(_sample_resume())
    sections = cv.sections or {}

    assert sections["Summary"] == ["Backend engineer."]

    exp = sections["Experience"][0]
    assert exp.company == "Acme"
    assert exp.position == "Senior Engineer"
    assert exp.start_date == "2023-01"
    assert exp.end_date == "present"

    exp2 = sections["Experience"][1]
    assert exp2.start_date == "2020-06"
    # Only start_date is normalized; end_date passes through unless ongoing.
    assert exp2.end_date == "12/2022"

    edu = sections["Education"][0]
    assert edu.institution == "MIT"
    assert edu.area == "Computer Science"
    assert edu.degree == "BS"
    assert edu.end_date == "2018-05"
    assert edu.highlights == ["Summa Cum Laude", "Dean's List"]

    assert sections["Skills"][0].bullet == "Languages: python, go"

    project = sections["Projects"][0]
    assert project.name == "Sidecar"
    assert project.highlights == ["1k stars", "**Technologies**: rust"]

    langs = sections["Languages"]
    assert (langs[0].label, langs[0].details) == ("English", "Native")
    assert (langs[1].label, langs[1].details) == ("German", "Level 2")

    assert sections["Interests"][0].bullet == "Climbing: boulder"


def test_conversion_skips_empty_sections() -> None:
    cv = parsed_resume_to_rendercv(ParsedResume())
    assert cv.sections is None
    assert cv.social_networks is None
    assert cv.email is None


def test_normalize_rendercv_date() -> None:
    assert normalize_rendercv_date("01/2023") == "2023-01"
    assert normalize_rendercv_date("Jan 2024") == "2024-01"
    assert normalize_rendercv_date("2023") == "2023"
    assert normalize_rendercv_date("") is None
    assert normalize_rendercv_date(None) is None


def test_normalize_phone_and_website() -> None:
    assert normalize_phone("+1 555") == "+1 555"
    assert normalize_phone("555-0100") is None
    assert normalize_website_url("janedoe.dev") == "https://janedoe.dev"
    assert normalize_website_url("http://x.dev") == "http://x.dev"


def test_make_end_date() -> None:
    assert make_end_date("", True) == "present"
    assert make_end_date("12/2022", False) == "12/2022"
    assert make_end_date("", False) is None


def test_network_name_mapping() -> None:
    assert normalize_network_name("GitHub") == "GitHub"
    assert try_normalize_network_name("Website") is None
    with pytest.raises(ValueError):
        normalize_network_name("UnknownThing")


def test_validate_render_options_defaults_and_valid() -> None:
    options = validate_render_options(None, None)
    assert (options.theme, options.locale) == ("classic", "english")
    options = validate_render_options("sb2nov", "vietnamese")
    assert (options.theme, options.locale) == ("sb2nov", "vietnamese")


def test_validate_render_options_rejects_unknown_theme() -> None:
    with pytest.raises(InvalidRenderOptionError) as exc_info:
        validate_render_options("nope", None)
    assert exc_info.value.code == "invalid_render_option"
    assert exc_info.value.details["option"] == "theme"
    assert "classic" in exc_info.value.details["supported"]


def test_validate_render_options_rejects_unknown_locale() -> None:
    with pytest.raises(InvalidRenderOptionError) as exc_info:
        validate_render_options(None, "klingon")
    assert exc_info.value.code == "invalid_render_option"
    assert exc_info.value.details["option"] == "locale"
