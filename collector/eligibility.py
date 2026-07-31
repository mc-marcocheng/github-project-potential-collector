from __future__ import annotations

import re
from dataclasses import dataclass

from collector.util import normalize_text


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    reasons: list[str]


EXCLUDED_REPOSITORY_NAMES = {
    ".dotfiles",
    "dotfiles",
    "homework",
    "coursework",
    "assignments",
    "node_modules",
    "dependency-cache",
    "package-cache",
}

ACADEMIC_PATTERNS = (
    re.compile(r"\bhomework\b", re.IGNORECASE),
    re.compile(r"\bcoursework\b", re.IGNORECASE),
    re.compile(r"\bproblem sets?\b", re.IGNORECASE),
    re.compile(r"\bclass assignments?\b", re.IGNORECASE),
    re.compile(r"\bassignment for\b", re.IGNORECASE),
)

DOCUSAURUS_TEMPLATE_MARKERS = (
    "this website is built using [docusaurus]",
    "a modern static website generator",
    "using ssh:",
    "not using ssh:",
    "npm run deploy",
)


def _repository_basename(full_name: str | None) -> str:
    if not full_name:
        return ""
    return full_name.rsplit("/", 1)[-1].strip().lower()


def _is_obvious_academic_repository(
    repository_name: str,
    description: str,
    readme: str,
) -> bool:
    inspected = "\n".join(
        (
            repository_name,
            description,
            readme[:2_000],
        )
    )
    return any(pattern.search(inspected) for pattern in ACADEMIC_PATTERNS)


def _is_template_only_readme(
    description: str,
    readme: str,
) -> bool:
    lowered = readme.lower()

    docusaurus_hits = sum(
        marker in lowered for marker in DOCUSAURUS_TEMPLATE_MARKERS
    )

    return (
        docusaurus_hits >= 4
        and len(description) < 80
        and len(readme) < 2_500
    )


def evaluate_eligibility(
    *,
    repository_status: str,
    full_name: str | None,
    private: bool,
    fork: bool,
    archived: bool,
    disabled: bool,
    mirror_url_present: bool,
    commit_sha: str | None,
    description: str | None,
    readme_text: str | None,
) -> EligibilityResult:
    reasons: list[str] = []

    description = normalize_text(description)
    readme = normalize_text(readme_text)
    repository_name = _repository_basename(full_name)

    if repository_status != "public" or private:
        reasons.append("not_public")
    if fork:
        reasons.append("fork")
    if archived:
        reasons.append("archived")
    if disabled:
        reasons.append("disabled")
    if mirror_url_present:
        reasons.append("mirror")
    if not commit_sha:
        reasons.append("missing_launch_commit")

    if len(description) < 80 and len(readme) < 200:
        reasons.append("insufficient_project_text")

    if repository_name in EXCLUDED_REPOSITORY_NAMES:
        reasons.append("excluded_repository_type")

    if _is_obvious_academic_repository(
        repository_name,
        description,
        readme,
    ):
        reasons.append("obvious_coursework")

    if _is_template_only_readme(description, readme):
        reasons.append("template_only_readme")

    return EligibilityResult(
        eligible=not reasons,
        reasons=reasons,
    )
