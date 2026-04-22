"""
Built-in skill catalog — reusable skills that any agent can be assigned.
Parents pick from here (or invent new ones) when spawning children.
"""
from dri.core.models import Skill


class SkillCatalog:
    """
    Registry of pre-defined skills.
    Access with SkillCatalog.get("web_research") or SkillCatalog.all().
    """

    _skills: dict[str, Skill] = {
        # ── Research ─────────────────────────────────────────
        "web_research": Skill(
            name="Web Research",
            description="Search the web to gather information, verify facts, and find resources.",
            instructions=(
                "Use the web_search tool to find relevant information. "
                "Always search with specific, targeted queries. "
                "Synthesize multiple sources and cite them in your result. "
                "Distinguish between verified facts and inferences."
            ),
            required_tools=["web_search"],
        ),
        # ── Writing ──────────────────────────────────────────
        "content_writing": Skill(
            name="Content Writing",
            description="Write high-quality, structured content (articles, reports, copy, etc.).",
            instructions=(
                "Write clearly and concisely. Structure content with headers and sections. "
                "Adapt tone to the target audience. "
                "Always produce complete, publication-ready text unless explicitly asked for a draft."
            ),
            required_tools=[],
        ),
        "technical_writing": Skill(
            name="Technical Writing",
            description="Produce technical documentation, specs, READMEs, and API docs.",
            instructions=(
                "Use precise, unambiguous language. Include examples and code snippets where relevant. "
                "Follow standard documentation conventions (markdown, docstrings, etc.). "
                "Structure for both quick scanning and deep reading."
            ),
            required_tools=["file_write"],
        ),
        # ── Code ─────────────────────────────────────────────
        "python_development": Skill(
            name="Python Development",
            description="Write, review, and execute Python code.",
            instructions=(
                "Write idiomatic Python 3.12+ with type hints. "
                "Follow PEP 8. Use async/await for I/O-bound work. "
                "Execute code with code_exec to verify correctness before delivering results. "
                "Handle errors explicitly — never use bare except."
            ),
            required_tools=["code_exec", "file_write", "file_read"],
        ),
        "code_review": Skill(
            name="Code Review",
            description="Review code for correctness, security, and quality.",
            instructions=(
                "Check for: bugs, security vulnerabilities (OWASP top 10), "
                "performance issues, and maintainability concerns. "
                "Provide specific, actionable feedback with line references. "
                "Distinguish between blocking issues and suggestions."
            ),
            required_tools=["file_read", "code_exec"],
        ),
        # ── Analysis ─────────────────────────────────────────
        "data_analysis": Skill(
            name="Data Analysis",
            description="Analyze data, identify patterns, and produce insights.",
            instructions=(
                "Use code_exec for quantitative analysis. "
                "Always validate data quality before drawing conclusions. "
                "Present findings with supporting evidence. "
                "Use charts/tables descriptions when visualizations would help."
            ),
            required_tools=["code_exec", "file_read"],
        ),
        "market_research": Skill(
            name="Market Research",
            description="Research markets, competitors, trends, and opportunities.",
            instructions=(
                "Search for industry data, competitor information, and market trends. "
                "Provide quantitative data where available (market size, growth rates). "
                "Identify key players, their strengths/weaknesses, and market gaps. "
                "Always note the date and source reliability of your findings."
            ),
            required_tools=["web_search"],
        ),
        # ── Management ───────────────────────────────────────
        "team_management": Skill(
            name="Team Management",
            description="Plan, delegate, supervise, and synthesize work across a team of sub-agents.",
            instructions=(
                "Break complex objectives into clear, independent subtasks. "
                "Assign tasks to the most appropriate sub-agent. "
                "Monitor results for quality and completeness. "
                "Synthesize sub-agent outputs into a coherent whole before reporting upward. "
                "Escalate blockers immediately rather than waiting."
            ),
            required_tools=[],
        ),
        "strategic_planning": Skill(
            name="Strategic Planning",
            description="Define vision, goals, and actionable plans for a company or department.",
            instructions=(
                "Think long-term (6-18 months) while maintaining near-term clarity. "
                "Define measurable goals (OKRs or KPIs). "
                "Identify dependencies, risks, and mitigation strategies. "
                "Produce structured plans with clear ownership and timelines."
            ),
            required_tools=[],
        ),
        # ── Operations ───────────────────────────────────────
        "file_management": Skill(
            name="File Management",
            description="Read, write, and organize files in the workspace.",
            instructions=(
                "Always work within the designated workspace directory. "
                "Use clear, descriptive filenames. "
                "Verify file contents after writing. "
                "Never overwrite files without checking existing contents first."
            ),
            required_tools=["file_read", "file_write", "file_list"],
        ),
        # ── Finance ──────────────────────────────────────────
        "financial_modeling": Skill(
            name="Financial Modeling",
            description="Build financial models, projections, and budgets.",
            instructions=(
                "Use code_exec for calculations. "
                "State all assumptions explicitly. "
                "Provide sensitivity analysis for key variables. "
                "Present results in clear tables with totals and subtotals."
            ),
            required_tools=["code_exec", "file_write"],
        ),
    }

    @classmethod
    def get(cls, name: str) -> Skill:
        skill = cls._skills.get(name)
        if skill is None:
            raise KeyError(f"Skill '{name}' not found in catalog. Available: {list(cls._skills)}")
        return skill

    @classmethod
    def get_many(cls, names: list[str]) -> list[Skill]:
        return [cls.get(n) for n in names]

    @classmethod
    def all(cls) -> list[Skill]:
        return list(cls._skills.values())

    @classmethod
    def names(cls) -> list[str]:
        return list(cls._skills.keys())

    @classmethod
    def register(cls, skill: Skill) -> None:
        """Allow runtime registration of custom skills."""
        cls._skills[skill.name.lower().replace(" ", "_")] = skill
