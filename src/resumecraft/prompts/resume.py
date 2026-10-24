GENERATE_RESUME_PROMPT = """\
You are an expert resume writer. Rewrite the candidate's resume so it targets the given role.

<resume>
{resume_text}
</resume>

<target_role>
{target_role}
</target_role>

Fill the structured resume: contact details, a concise professional summary, work
experience with quantified achievements, education, categorized skills, and any
projects, certifications or other sections the resume supports. Use action verbs
and quantified impact where possible. Leave a section empty rather than inventing
facts — never fabricate employers, degrees, dates or metrics.
"""

PARSE_RESUME_PROMPT = """\
You are a precise resume parser. Extract the candidate's resume into structured data.

<resume>
{resume_text}
</resume>

Extract faithfully — every employer, title, date, school, skill and URL must come
from the resume itself. Do not rewrite, improve or invent anything; leave fields
empty when the resume does not state them. Normalizations that are allowed:
expanding obvious abbreviations in skill names, and deriving is_current when the
resume says "present".
"""
