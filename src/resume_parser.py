"""Resume-to-Profile auto-generator — parse RESUME.md or PDF to generate profile.yaml.

Extracts structured profile data from a user's resume, eliminating the biggest
onboarding friction: manually re-typing skills, location, experience level, and
target roles that are already in the resume.

Data flow:
  RESUME.md or *.pdf (project root)
        │
  ┌─────────────────────────────────────────────────────┐
  │  Markdown: read text directly                       │
  │  PDF: PyMuPDF (fitz) text extraction                │
  └─────────────────────────────────────────────────────┘
        │
  regex extraction pipelines:
        │
  ┌─────────────────────────────────────────────────────┐
  │  extract_name()    → first heading / bold line      │
  │  extract_location()→ "City, ST" or "City, Province" │
  │  extract_years()   → years from job date ranges     │
  │  extract_skills()  → skills table / section parsing │
  │  extract_roles()   → job titles from experience     │
  │  extract_email()   → email from header              │
  └─────────────────────────────────────────────────────┘
        │
  generate_profile() → dict (YAML-serializable)
        │
  config/profile.yaml (written with comments)

Shadow paths:
  No RESUME.md or PDF → FileNotFoundError
  Empty resume        → ValueError("Resume is empty")
  No skills found     → skills: [] (user must fill manually)
  No location found   → location: "" (user must fill)
  PDF parse error     → falls back to RESUME.md
"""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from src.config import PROJECT_ROOT, CONFIG_DIR

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

# Common tech skills to look for (case-insensitive word-boundary match)
# This is a superset — we extract whatever appears in the resume.
KNOWN_SKILLS = [
    # Languages
    "Java", "Kotlin", "Python", "TypeScript", "JavaScript", "Go", "Rust", "C++",
    "C#", "Ruby", "PHP", "Scala", "Swift", "Objective-C", "R", "Matlab", "Perl",
    "Shell", "Bash", "SQL", "HTML", "CSS",
    # Frameworks & Libraries
    "Spring Boot", "Spring", "React", "Angular", "Vue", "Node.js", "Express",
    "Django", "Flask", "FastAPI", "Rails", "Next.js", "Svelte",
    "Redux", "GraphQL", "REST", "gRPC",
    # Cloud & Infrastructure
    "AWS", "GCP", "Azure", "Docker", "Kubernetes", "Terraform", "CloudFormation",
    "CDK", "Lambda", "ECS", "EC2", "S3",
    # Databases
    "PostgreSQL", "MySQL", "MongoDB", "Redis", "DynamoDB", "Cassandra",
    "Elasticsearch", "SQLite", "Oracle",
    # Data & ML
    "Spark", "Kafka", "Airflow", "dbt", "Snowflake", "BigQuery", "Redshift",
    "Pandas", "NumPy", "TensorFlow", "PyTorch", "scikit-learn",
    # Tools
    "Git", "GitHub", "Jenkins", "CI/CD", "Maven", "Gradle",
    "Docker", "Figma", "Jira",
    # Concepts (selectively — only ones that commonly appear as requirements)
    "Microservices", "Distributed Systems", "Event-Driven Architecture",
    "Machine Learning", "Data Engineering", "DevOps",
    "OAuth", "JWT", "REST APIs",
]

# Location patterns — "City, ST" or "City, Province" or "City, Country"
LOCATION_RE = re.compile(
    r'(?:^|\||\n)\s*'
    r'(?:Location:\s*|Based in\s+|Relocating (?:from|to)\s+\w+\s+to\s+)?'
    r'([A-Z][a-z]+(?:\s[A-Z][a-z]+)?,\s*(?:[A-Z]{2}|[A-Z][a-z]+))'
    r'(?:\s|$|\||—)',
    re.MULTILINE
)

# Email pattern
EMAIL_RE = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')

# Year range in job experience — "2020 – Present" or "2016 - 2020" or "May 2024 – Present"
YEAR_RE = re.compile(
    r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|'
    r'Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)?'
    r'\s*(\d{4})\s*[-–—]\s*'
    r'(?:(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|'
    r'Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)?'
    r'\s*(\d{4})|[Pp]resent|[Cc]urrent)',
    re.IGNORECASE
)

# Job title patterns — lines starting with ### or containing common title words
TITLE_RE = re.compile(
    r'(?:^#{1,4}\s+)?'               # optional markdown heading
    r'((?:Senior\s+|Staff\s+|Lead\s+|Principal\s+|Junior\s+)?'
    r'(?:Software\s+(?:Development\s+)?Engineer|'
    r'Backend\s+Engineer|'
    r'Frontend\s+Engineer|'
    r'Full[- ]?Stack\s+Engineer|'
    r'Data\s+(?:Engineer|Scientist|Analyst)|'
    r'Machine\s+Learning\s+Engineer|'
    r'DevOps\s+Engineer|'
    r'SRE|Site\s+Reliability\s+Engineer|'
    r'Platform\s+Engineer|'
    r'Applications?\s+Engineer(?:\s+II?I?)?|'
    r'Solutions?\s+Architect|'
    r'Product\s+Manager|'
    r'Engineering\s+Manager|'
    r'Technical\s+(?:Program\s+|Project\s+)?Manager))',
    re.IGNORECASE | re.MULTILINE
)

# Experience level mapping based on years
LEVEL_MAP = [
    (0, 2, "entry"),
    (2, 5, "mid"),
    (5, 10, "senior"),
    (10, 15, "staff"),
    (15, 99, "principal"),
]


# ── Text Extraction ──────────────────────────────────────────────────────────

def read_resume_text(path: Path | None = None) -> str:
    """Read resume text from RESUME.md or PDF in project root.

    Tries in order:
      1. Explicit path argument
      2. RESUME.md in project root
      3. First *.pdf in project root

    Returns:
        Plain text content of the resume.

    Raises:
        FileNotFoundError: If no resume file found.
        ValueError: If resume is empty.
    """
    if path:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Resume not found: {path}")
        text = _read_file(path)
    else:
        md_path = PROJECT_ROOT / "RESUME.md"
        if md_path.exists():
            text = _read_file(md_path)
            log.info("Reading resume from %s", md_path)
        else:
            # Try first PDF in project root
            pdfs = sorted(PROJECT_ROOT.glob("*.pdf"))
            if pdfs:
                text = _read_file(pdfs[0])
                log.info("Reading resume from %s", pdfs[0])
            else:
                raise FileNotFoundError(
                    "No resume found. Create RESUME.md or place a PDF in the project root."
                )

    if not text or len(text.strip()) < 50:
        raise ValueError("Resume is empty or too short to parse.")

    return text


def _read_file(path: Path) -> str:
    """Read text from a .md or .pdf file."""
    if path.suffix.lower() == ".pdf":
        return _read_pdf(path)
    return path.read_text(encoding="utf-8")


def _read_pdf(path: Path) -> str:
    """Extract text from a PDF using PyMuPDF."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        log.warning("PyMuPDF not installed — cannot read PDF. Install with: pip install pymupdf")
        return ""

    try:
        doc = fitz.open(str(path))
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc.close()
        return "\n".join(text_parts)
    except Exception as e:
        log.warning("Failed to read PDF %s: %s", path, e)
        return ""


# ── Field Extraction ─────────────────────────────────────────────────────────

def extract_name(text: str) -> str:
    """Extract name from the first heading or bold line.

    Tries:
      1. First markdown heading: "# John Doe"
      2. First bold text: "**John Doe**"
      3. First non-empty line
    """
    # Try markdown heading
    m = re.search(r'^#\s+(.+)$', text, re.MULTILINE)
    if m:
        name = m.group(1).strip()
        # Clean up common suffixes (dash, em-dash, pipe)
        name = re.sub(r'\s*[-–—|].*$', '', name)
        return name

    # Try bold text
    m = re.search(r'\*\*([A-Z][a-z]+ [A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\*\*', text)
    if m:
        return m.group(1).strip()

    # Fallback: first non-empty line
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and len(line) < 50:
            return line

    return ""


def extract_email(text: str) -> str:
    """Extract first email address from text."""
    m = EMAIL_RE.search(text)
    return m.group(0) if m else ""


def extract_location(text: str) -> str:
    """Extract location (City, State/Province) from resume text.

    Handles patterns like:
      - "Toronto, ON"
      - "San Francisco, CA"
      - "relocating from the US to Canada" → looks for explicit city
      - "Based in New York, NY"
    """
    # Look in first ~500 chars (header area)
    header = text[:500]

    # Try explicit location patterns
    matches = LOCATION_RE.findall(header)
    if matches:
        return matches[0].strip()

    # Broader search in full text for "City, ST" pattern
    m = re.search(
        r'([A-Z][a-z]+(?:\s[A-Z][a-z]+)?,\s*(?:[A-Z]{2}|ON|BC|AB|QC|MB|SK|NS|NB|PE|NL|NT|NU|YT))\b',
        text[:1000]
    )
    if m:
        return m.group(1).strip()

    # Extract from job experience headers: "Company, City, ST — Date"
    m = re.search(
        r',\s*([A-Z]{2}),\s*(?:USA|US|Canada|UK)\s*[-–—]',
        text[:2000]
    )
    if m:
        state = m.group(1)
        # Map state abbreviations to major cities for a reasonable default
        STATE_CITIES = {
            "AZ": "Phoenix, AZ", "CA": "San Francisco, CA", "NY": "New York, NY",
            "TX": "Austin, TX", "WA": "Seattle, WA", "MA": "Boston, MA",
            "IL": "Chicago, IL", "CO": "Denver, CO", "GA": "Atlanta, GA",
            "ON": "Toronto, ON", "BC": "Vancouver, BC", "AB": "Calgary, AB",
        }
        if state in STATE_CITIES:
            return STATE_CITIES[state]

    return ""


def extract_years_experience(text: str) -> int:
    """Calculate total years of experience from job date ranges.

    Parses patterns like "May 2024 – Present", "Aug 2020 – May 2024".
    Returns total years (rounded).
    """
    # First check for explicit "X+ years" claims
    m = re.search(r'(\d+)\+?\s*years?\s*(?:of\s+)?experience', text, re.IGNORECASE)
    if m:
        return int(m.group(1))

    # Parse date ranges from experience section
    current_year = date.today().year
    years = []
    for match in YEAR_RE.finditer(text):
        start_year = int(match.group(1))
        end_str = match.group(2)
        end_year = int(end_str) if end_str and end_str.isdigit() else current_year
        if 1990 <= start_year <= current_year and start_year <= end_year:
            years.append((start_year, end_year))

    if not years:
        return 0

    # Use earliest start to latest end (accounts for overlapping roles)
    earliest = min(y[0] for y in years)
    latest = max(y[1] for y in years)
    return latest - earliest


def extract_skills(text: str) -> list[str]:
    """Extract technical skills from resume text.

    Strategy:
      1. Look for a skills section (table or list)
      2. Match against KNOWN_SKILLS using word boundaries
      3. Deduplicate preserving order
    """
    found = []
    seen = set()

    text_lower = text.lower()
    for skill in KNOWN_SKILLS:
        if skill.lower() in seen:
            continue
        # Word-boundary match
        pattern = r'\b' + re.escape(skill.lower()) + r'\b'
        if re.search(pattern, text_lower):
            found.append(skill)
            seen.add(skill.lower())

    return found


def extract_roles(text: str) -> list[str]:
    """Extract job titles from experience section.

    Returns deduplicated, normalized role titles suitable for target_roles.
    """
    roles = []
    seen = set()

    for match in TITLE_RE.finditer(text):
        role = match.group(1).strip()
        # Normalize whitespace
        role = re.sub(r'\s+', ' ', role)
        # Remove trailing roman numerals for generic matching
        role = re.sub(r'\s+I{1,3}$', '', role)
        role_lower = role.lower()
        if role_lower not in seen:
            roles.append(role)
            seen.add(role_lower)

    return roles


def infer_target_level(years: int) -> str:
    """Infer target seniority level from years of experience."""
    for low, high, level in LEVEL_MAP:
        if low <= years < high:
            return level
    return "senior"


def infer_exclude_levels(target_level: str) -> list[str]:
    """Infer which levels to exclude based on target level."""
    levels = ["intern", "entry", "mid", "senior", "lead", "manager"]
    target_idx = levels.index(target_level) if target_level in levels else 2
    # Exclude levels more than 2 below target
    return [l for i, l in enumerate(levels) if i < target_idx - 1]


# ── Profile Generation ────────────────────────────────────────────────────────

def generate_profile(text: str) -> dict[str, Any]:
    """Generate a complete profile dict from resume text.

    Returns a dict matching the config/profile.yaml schema, ready to be
    written as YAML. All fields are populated with best-effort extraction
    or sensible defaults.
    """
    name = extract_name(text)
    email = extract_email(text)
    location = extract_location(text)
    years = extract_years_experience(text)
    skills = extract_skills(text)
    roles = extract_roles(text)
    level = infer_target_level(years)
    exclude = infer_exclude_levels(level)

    # Build target_roles: extracted titles + generalized versions
    target_roles = []
    seen = set()
    for role in roles:
        if role.lower() not in seen:
            target_roles.append(role)
            seen.add(role.lower())
        # Add generalized version (without Senior/Staff/Lead prefix)
        generic = re.sub(r'^(?:Senior|Staff|Lead|Principal|Junior)\s+', '', role, flags=re.IGNORECASE)
        if generic.lower() not in seen:
            target_roles.append(generic)
            seen.add(generic.lower())

    # Build boost_keywords from skills (first 8)
    boost_keywords = [s.lower() for s in skills[:8]]

    profile = {
        "name": name,
        "email": email,
        "location": location,
        "willing_to_relocate": True,
        "relocation_cities": [],
        "remote_ok": True,
        "years_experience": years,
        "target_level": level,
        "exclude_levels": exclude,
        "target_roles": target_roles[:8],  # cap at 8 for focused matching
        "skills": skills[:15],              # cap at 15 most relevant
        "boost_keywords": boost_keywords,
        "preferred_companies": {
            "greenhouse": [],
            "lever": [],
            "ashby": [],
        },
        "exclude_title_patterns": [],
        "metro_cities": [],
        "exclude_recruiters": True,
        "exclude_staffing": True,
    }

    return profile


def write_profile(profile: dict, path: Path | None = None, force: bool = False) -> Path:
    """Write profile dict to YAML file with header comments.

    Args:
        profile: Profile dict from generate_profile().
        path: Output path. Defaults to config/profile.yaml.
        force: Overwrite existing file. Default False.

    Returns:
        Path to written file.

    Raises:
        FileExistsError: If file exists and force=False.
    """
    if path is None:
        path = CONFIG_DIR / "profile.yaml"
    path = Path(path)

    if path.exists() and not force:
        raise FileExistsError(
            f"Profile already exists at {path}. Use force=True to overwrite, "
            f"or delete the file first."
        )

    path.parent.mkdir(parents=True, exist_ok=True)

    header = (
        "# JobHunter AI — User Profile (auto-generated from resume)\n"
        "#\n"
        "# ⚠️  Review and customize! This was auto-generated from your resume.\n"
        "# Key fields to review:\n"
        "#   - target_roles: Are these the jobs you're looking for?\n"
        "#   - location: Is this where you want to work?\n"
        "#   - relocation_cities: Add cities you'd move to\n"
        "#   - preferred_companies: Add companies you're targeting\n"
        "#   - metro_cities: Add nearby cities for location matching\n"
        "#\n"
        "# After editing, re-run the pipeline: /jobhunter or python -m src.matcher\n"
        "\n"
    )

    yaml_content = yaml.dump(
        profile,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )

    path.write_text(header + yaml_content, encoding="utf-8")
    log.info("Profile written to %s", path)
    return path


# ── Pipeline ──────────────────────────────────────────────────────────────────

def run_resume_parser(
    resume_path: str | Path | None = None,
    output_path: str | Path | None = None,
    force: bool = False,
) -> dict:
    """Parse resume and generate profile.yaml.

    Args:
        resume_path: Path to resume file. Auto-detects if None.
        output_path: Path to write profile. Defaults to config/profile.yaml.
        force: Overwrite existing profile.yaml.

    Returns:
        Summary dict with extracted fields and output path.
    """
    text = read_resume_text(Path(resume_path) if resume_path else None)
    profile = generate_profile(text)
    out = write_profile(
        profile,
        path=Path(output_path) if output_path else None,
        force=force,
    )

    summary = {
        "name": profile["name"],
        "location": profile["location"],
        "years_experience": profile["years_experience"],
        "target_level": profile["target_level"],
        "skills_found": len(profile["skills"]),
        "roles_found": len(profile["target_roles"]),
        "output_path": str(out),
    }

    log.info(
        "Profile generated: %s, %s, %d years, %d skills, %d roles",
        profile["name"], profile["location"],
        profile["years_experience"], len(profile["skills"]),
        len(profile["target_roles"]),
    )

    return summary


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import json

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Parse resume to generate profile.yaml")
    parser.add_argument("--resume", type=str, default=None, help="Path to resume file")
    parser.add_argument("--output", type=str, default=None, help="Path to write profile")
    parser.add_argument("--force", action="store_true", help="Overwrite existing profile")
    parser.add_argument("--dry-run", action="store_true", help="Print profile without writing")
    args = parser.parse_args()

    if args.dry_run:
        text = read_resume_text(Path(args.resume) if args.resume else None)
        profile = generate_profile(text)
        print(yaml.dump(profile, default_flow_style=False, sort_keys=False))
    else:
        result = run_resume_parser(
            resume_path=args.resume,
            output_path=args.output,
            force=args.force,
        )
        print(f"\n{json.dumps(result, indent=2)}")
