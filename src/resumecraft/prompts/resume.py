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
