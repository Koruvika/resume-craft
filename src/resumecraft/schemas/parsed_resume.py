"""ParsedResume: the canonical structured resume format (shared with resumebloom).

Both LLM flows (generate/parse) produce this via structured output, uploads accept
it as JSON, and it is what gets stored in `resumes.content` as JSONB.

Copied from resumebloom backend `app/llm/types.py` — keep the two in sync.
"""

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class ContactInfo(BaseModel):
    """Extracted contact information from a resume."""

    full_name: str = Field(default="", description="Full name")
    headline: str = Field(
        default="", description="Professional headline, e.g. Senior Backend Engineer"
    )
    email: str = Field(default="", description="Primary email address")
    emails: list[str] = Field(
        default_factory=list, description="All email addresses (primary first)"
    )
    phone: str = Field(default="", description="Primary phone number")
    phones: list[str] = Field(default_factory=list, description="All phone numbers (primary first)")
    location: str = Field(default="", description="City, state, country")
    linkedin_url: str = Field(default="", description="LinkedIn profile URL")
    portfolio_url: str = Field(default="", description="Personal website URL")
    photo_url: str = Field(default="", description="Photo URL or path")
    additional_info: str = Field(default="", description="Additional contact information")
    website: str = Field(default="", description="Personal website URL")

    @field_validator("emails", mode="before")
    @classmethod
    def coerce_emails_none(cls, v: Any) -> Any:
        return [] if v is None else v

    @field_validator("phones", mode="before")
    @classmethod
    def coerce_phones_none(cls, v: Any) -> Any:
        return [] if v is None else v

    @model_validator(mode="after")
    def sync_primary_fields(self) -> "ContactInfo":
        if self.emails and not self.email:
            self.email = self.emails[0]
        if self.phones and not self.phone:
            self.phone = self.phones[0]
        return self


class EducationEntry(BaseModel):
    """A single education entry."""

    degree: str = Field(default="", description="Degree, diploma, etc.")
    institution: str = Field(default="", description="School, university, or college")
    location: str = Field(default="", description="City, state, country of institution")
    start_date: str | None = Field(default=None, description="Start date of the program")
    graduation_date: str = Field(
        default="", description="Graduation date or expected graduation date"
    )
    gpa: str = Field(default="", description="GPA or equivalent")
    honors: str = Field(default="", description="Awards, certificates, research achievement, etc.")
    area: str = Field(
        default="", description="Field of study or specialization, e.g. Computer Science"
    )
    description: str = Field(
        default="", description="Additional details: coursework, thesis, activities"
    )
    highlights: list[str] = Field(
        default_factory=list,
        description="Bullet points for key achievements, honors, or relevant coursework",
    )
    website: str = Field(default="", description="Institution URL")

    @field_validator("highlights", mode="before")
    @classmethod
    def coerce_highlights_none(cls, v: Any) -> Any:
        return [] if v is None else v


class SkillsGroup(BaseModel):
    """A group of skills with common attributes."""

    category: str | None = Field(
        default=None, description="Category, e.g. Programming Languages, Frameworks, Soft Skills"
    )
    skills: list[str] = Field(default_factory=list, description="List of skills in this group")

    @field_validator("skills", mode="before")
    @classmethod
    def normalize_skills_field(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        if isinstance(v, list):
            result = []
            for item in v:
                if isinstance(item, str):
                    result.append(item.strip())
                else:
                    result.append(str(item))
            return result
        return v if isinstance(v, list) else []


class SkillsSection(BaseModel):
    """Skills extracted from a résumé — flexible input, canonical output.

    Accepts 4 input formats:
    1. Dict with category→skills: {"Technology": ["python", "LLM"]}
    2. Flat list: ["python", "LLM", "AWS", "Sales"]
    3. Comma-separated string: "python, LLM, AWS, Sales"
    4. Categorized strings: ["Technology: python, LLM", "Marketing: Sales"]

    Always normalizes to groups: list[SkillsGroup].
    """

    groups: list[SkillsGroup] = Field(default_factory=list, description="Skill groups")

    @model_validator(mode="before")
    @classmethod
    def normalize_skills(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "groups" in data:
                return data
            return {"groups": cls._dict_to_groups(data)}
        if isinstance(data, list):
            return {"groups": cls._list_to_groups(data)}
        if isinstance(data, str):
            return {"groups": cls._string_to_groups(data)}
        return data

    @classmethod
    def _dict_to_groups(cls, raw: dict) -> list[dict]:
        groups: list[dict] = []
        for key, val in raw.items():
            if key == "groups":
                continue
            if isinstance(val, list):
                skills: list[str] = []
                for item in val:
                    if isinstance(item, str) and "," in item:
                        skills.extend(s.strip() for s in item.split(",") if s.strip())
                    elif isinstance(item, str):
                        skills.append(item.strip())
                    else:
                        skills.append(str(item))
                groups.append({"category": key, "skills": skills})
            elif isinstance(val, str):
                skills = [s.strip() for s in val.split(",") if s.strip()]
                groups.append({"category": key, "skills": skills})
        return groups

    @classmethod
    def _list_to_groups(cls, raw: list) -> list[dict]:
        groups: list[dict] = []
        uncategorized: list[str] = []
        for item in raw:
            if isinstance(item, str) and ":" in item:
                category, _, rest = item.partition(":")
                category = category.strip()
                skills = [s.strip() for s in rest.split(",") if s.strip()]
                if category and skills:
                    groups.append({"category": category, "skills": skills})
                else:
                    uncategorized.extend(s.strip() for s in rest.split(",") if s.strip())
            elif isinstance(item, str):
                uncategorized.append(item.strip())
            elif isinstance(item, dict):
                groups.append(item)
        if uncategorized:
            groups.append({"category": None, "skills": uncategorized})
        return groups

    @classmethod
    def _string_to_groups(cls, raw: str) -> list[dict]:
        groups = [group.strip() for group in raw.replace("|", "\n").split("\n") if group.strip()]
        results: list[dict] = []
        for group in groups:
            split_group = group.split(":")
            if len(split_group) > 1:
                category, skills_text = split_group
            else:
                category, skills_text = None, group
            skills = [s.strip() for s in skills_text.split(",") if s.strip()]
            results.append(
                {
                    "category": category.strip() if category else None,
                    "skills": skills,
                }
            )

        return results


class ProjectEntry(BaseModel):
    """A single project entry."""

    name: str = Field(default="", description="Project name")
    description: str = Field(default="", description="Project description")
    technologies: list[str] | None = Field(default=None, description="Technologies used")
    achievements: list[str] = Field(
        default_factory=list,
        description="Project achievements, contributions, anything valuable you did in project",
    )
    url: str = Field(default="", description="Project URL")

    @field_validator("technologies", mode="before")
    @classmethod
    def coerce_none_to_list(cls, v: Any) -> Any:
        return [] if v is None else v

    @field_validator("url", mode="before")
    @classmethod
    def coerce_none_to_str(cls, v: Any) -> Any:
        return "" if v is None else v


class ExperienceEntry(BaseModel):
    """A single work experience entry."""

    job_title: str = Field(default="", description="Job title")
    company: str = Field(default="", description="Company name")
    location: str = Field(default="", description="City, state, country of company")
    start_date: str = Field(default="", description="Start date or expected start date")
    end_date: str = Field(default="", description="End date or expected end date")
    is_current: bool = Field(default=False, description="Whether the job is still in progress")
    summary: str = Field(default="", description="Brief overview of the role, 1-2 sentences")
    achievements: list[str] = Field(
        default_factory=list,
        description="Job achievements, contributions, anything valuable you did in this job",
    )
    website: str = Field(default="", description="Company website URL")

    @field_validator("achievements", mode="before")
    @classmethod
    def coerce_achievements_none(cls, v: Any) -> Any:
        return [] if v is None else v


class LanguageEntry(BaseModel):
    """A language the candidate speaks."""

    language: str = Field(default="", description="Language name, e.g. English, Vietnamese")
    fluency: str = Field(default="", description="Fluency level, e.g. Native, Fluent, B2")
    level: int = Field(default=0, ge=0, le=5, description="Numeric proficiency 0-5 (0=unspecified)")


class AwardEntry(BaseModel):
    """An award or honor received."""

    title: str = Field(default="", description="Award title")
    awarder: str = Field(default="", description="Awarding organization")
    date: str = Field(default="", description="Date received")
    description: str = Field(default="", description="Award description")
    website: str = Field(default="", description="URL for the award")


class CertificationEntry(BaseModel):
    """A professional certification."""

    title: str = Field(default="", description="Certification title")
    issuer: str = Field(default="", description="Issuing organization, e.g. AWS, Google")
    date: str = Field(default="", description="Date obtained")
    description: str = Field(default="", description="Certification description")
    website: str = Field(default="", description="Verification URL")


class VolunteerEntry(BaseModel):
    """A volunteer experience entry."""

    organization: str = Field(default="", description="Organization name")
    position: str = Field(default="", description="Role/position held")
    location: str = Field(default="", description="Location")
    description: str = Field(default="", description="Description of volunteer work")
    website: str = Field(default="", description="Organization URL")


class PublicationEntry(BaseModel):
    """A publication (paper, article, book)."""

    title: str = Field(default="", description="Publication title")
    authors: list[str] = Field(default_factory=list, description="List of author names")
    journal: str = Field(default="", description="Journal, conference, or venue name")
    publisher: str = Field(default="", description="Publisher or institution")
    date: str = Field(default="", description="Publication date")
    doi: str = Field(default="", description="DOI identifier, e.g. 10.1234/abc123")
    description: str = Field(default="", description="Summary or abstract")
    website: str = Field(default="", description="URL to the publication")

    @field_validator("authors", mode="before")
    @classmethod
    def coerce_authors_none(cls, v: Any) -> Any:
        return [] if v is None else v


class ReferenceEntry(BaseModel):
    """A professional reference."""

    name: str = Field(default="", description="Reference's full name")
    position: str = Field(default="", description="Reference's job title")
    phone: str = Field(default="", description="Reference's phone number")
    description: str = Field(default="", description="Testimonial or relationship note")
    website: str = Field(default="", description="LinkedIn or professional URL")


class ProfileEntry(BaseModel):
    """An online profile or social media account."""

    network: str = Field(default="", description="Platform name, e.g. GitHub, LinkedIn, Twitter")
    username: str = Field(default="", description="Username on the platform")
    url: str = Field(default="", description="Full profile URL")


class InterestEntry(BaseModel):
    """A personal interest or hobby."""

    name: str = Field(default="", description="Interest name, e.g. Open Source, Rock Climbing")
    keywords: list[str] = Field(default_factory=list, description="Related tags or sub-interests")


class ParsedResume(BaseModel):
    """Complete parsed resume structure.

    The canonical resume shape for resumecraft: LLM generation and parsing
    produce it, uploads accept it, and it is stored in `resumes.content`.
    """

    contact_info: ContactInfo = Field(default_factory=ContactInfo, description="Contact details")
    summary: str = Field(default="", description="Personal statement, if available")
    experience: list[ExperienceEntry] = Field(default_factory=list, description="Work experience")
    education: list[EducationEntry] = Field(default_factory=list, description="Education")
    skills: SkillsSection = Field(default_factory=SkillsSection, description="Skill section")
    projects: list[ProjectEntry] = Field(
        default_factory=list, description="Side projects or SaaS, not included in work experience"
    )
    languages: list[LanguageEntry] = Field(default_factory=list, description="Languages spoken")
    awards: list[AwardEntry] = Field(default_factory=list, description="Awards and honors")
    certifications: list[CertificationEntry] = Field(
        default_factory=list, description="Professional certifications"
    )
    volunteer: list[VolunteerEntry] = Field(
        default_factory=list, description="Volunteer experience"
    )
    publications: list[PublicationEntry] = Field(
        default_factory=list, description="Publications (papers, articles, books)"
    )
    references: list[ReferenceEntry] = Field(
        default_factory=list, description="Professional references"
    )
    profiles: list[ProfileEntry] = Field(
        default_factory=list, description="Online profiles and social media accounts"
    )
    interests: list[InterestEntry] = Field(
        default_factory=list, description="Personal interests and hobbies"
    )
