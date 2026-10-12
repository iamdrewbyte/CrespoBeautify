"""Default house rules for the AI review. Used when a template has no `ai:` lines.

Each rule is one short, checkable sentence: a 7B model follows a concrete rule far better than a vague one.
"""

TECHNICAL = [
    "Formal, objective, third-person tone. No first person (I, we, our), slang, humour, exclamation marks or contractions (don't, can't).",
    "Each finding states what was found, why it matters (impact) and how to fix it (recommendation). Flag a finding that is missing one of the three.",
    "Describe evidence factually: say 'was observed' or 'was identified', not 'obviously', 'clearly', 'very bad' or 'easily hacked'.",
    "Use precise, measured wording. Avoid vague words such as 'stuff', 'things', 'a lot', 'maybe', 'probably', 'kind of', 'etc.'.",
    "Severity names are exactly: Critical, High, Medium, Low, Informational. No other spellings such as 'Severe', 'Moderate', 'Info' or 'Minor'.",
    "Client name, dates and the consultant's name are written the same way throughout the report.",
    "No draft wording or notes to self: TBD, TODO, XXX, lorem ipsum, 'see above', unfilled [brackets] or {{tokens}}.",
    "Sentences are complete and clear: no run-on sentences, repeated words, or abbreviations that are not explained on first use.",
    "Recommendations start with an action verb (Enforce, Disable, Upgrade, Restrict) and say what to change, not just that a problem exists.",
    "Headings, table labels and bullet lists use consistent capitalisation, punctuation and tense.",
]

EXECUTIVE = [
    "Plain language for a non-technical reader. Avoid unexplained jargon, command lines, ports, IP addresses and CVE identifiers.",
    "The opening summary states the overall risk level and what it means for the business.",
    "Formal, objective, third-person tone. No first person (I, we, our), slang, humour, exclamation marks or contractions.",
    "Explain impact in business terms (data exposure, downtime, financial, legal or reputational harm), not only technical terms.",
    "Avoid alarmist or vague wording such as 'catastrophic', 'very dangerous', 'hackers will easily'. State the risk factually.",
    "Severity names are exactly: Critical, High, Medium, Low, Informational. No other spellings.",
    "Client name, dates and the consultant's name are written the same way throughout the report.",
    "No draft wording or notes to self: TBD, TODO, XXX, lorem ipsum, unfilled [brackets] or {{tokens}}.",
    "Recommendations are specific, actionable and prioritised (what to fix first).",
    "Sentences are short and clear: no run-on sentences or repeated words.",
]


def defaults_for(report_type: str) -> list[str]:
    return list(TECHNICAL if report_type == "technical" else EXECUTIVE)
