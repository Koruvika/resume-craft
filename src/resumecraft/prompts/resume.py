GENERATE_RESUME_PROMPT = """\
You are an expert resume writer. Rewrite the candidate's resume so it targets the given role.

<resume>
{resume_text}
</resume>

<target_role>
{target_role}
</target_role>

Produce a polished resume: a strong title, a concise professional summary, 3-5 career
highlights, and a curated list of relevant skills. Use action verbs and quantified impact
where possible.
"""
