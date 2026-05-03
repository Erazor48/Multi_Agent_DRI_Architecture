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
        # ── Web Development ──────────────────────────────────
        "nextjs_development": Skill(
            name="Next.js Development",
            description="Build and maintain Next.js applications with TypeScript, Tailwind CSS, and shadcn/ui.",
            instructions=(
                "## Scaffold a new project\n"
                "```\n"
                "bun create next-app@latest <app-name> --typescript --tailwind --eslint --app --src-dir --import-alias '@/*' --yes\n"
                "```\n\n"
                "## Initialize shadcn/ui (run once, inside project dir)\n"
                "```\n"
                "bunx shadcn@latest init --defaults --yes\n"
                "```\n\n"
                "## Add shadcn components (non-interactive)\n"
                "```\n"
                "bunx shadcn@latest add button card input table dialog --yes\n"
                "```\n\n"
                "## Install deps, build, dev\n"
                "```\n"
                "bun install          # install / update packages\n"
                "bun run build        # production build — MUST pass with zero errors\n"
                "bun run dev          # start dev server (use only to verify, don't block)\n"
                "```\n\n"
                "## Rules\n"
                "- Always use `cwd` pointing to the project folder for all commands.\n"
                "- Run `bun run build` after EVERY change and fix ALL TypeScript/Tailwind errors.\n"
                "- Never fabricate component names — only use components that exist in the project.\n"
                "- Use `file_list` to verify generated files before reporting done.\n"
                "- For interactive CLI tools, always pass `--yes` or `--defaults` to avoid hanging.\n"
                "- Tailwind v4: use CSS variables in `globals.css`, NOT `tailwind.config.js`.\n"
                "- shadcn/ui components live in `src/components/ui/` — import from `@/components/ui/<name>`.\n"
            ),
            required_tools=["shell_exec", "file_write", "file_read", "file_list"],
        ),
        "frontend_development": Skill(
            name="Frontend Development",
            description="Build web UIs with React, TypeScript, CSS/Tailwind — within an existing project.",
            instructions=(
                "## Working within an existing Next.js project\n"
                "- ALWAYS call `file_list` on the project root first to understand the existing structure.\n"
                "- Read `package.json` to know the exact installed versions before writing any code.\n"
                "- Read `src/app/globals.css` and `src/app/layout.tsx` before modifying styles.\n"
                "- Import existing shadcn components from `@/components/ui/<name>` — don't recreate them.\n\n"
                "## Adding new shadcn components\n"
                "```\n"
                "bunx shadcn@latest add <component-name> --yes\n"
                "```\n"
                "Available components: accordion, alert, avatar, badge, button, calendar, card, checkbox, "
                "command, dialog, dropdown-menu, form, input, label, navigation-menu, popover, "
                "progress, radio-group, select, separator, sheet, skeleton, slider, switch, table, "
                "tabs, textarea, toast, toggle, tooltip.\n\n"
                "## Quality rules\n"
                "- Run `bun run build` after EVERY change — fix all errors before reporting done.\n"
                "- No `any` types in TypeScript — use proper interfaces.\n"
                "- No inline styles — use Tailwind utility classes.\n"
                "- Verify every file you write actually exists with `file_list` before reporting.\n"
            ),
            required_tools=["shell_exec", "file_write", "file_read", "file_list"],
        ),
        # ── Video ────────────────────────────────────────────
        "manim_video_creation": Skill(
            name="Manim Video Creation",
            description="Create animated videos using the Manim Python library.",
            instructions=(
                "## What is Manim\n"
                "Manim (Mathematical Animation Engine) creates smooth animated videos from Python scripts. "
                "Output format: MP4. Used for explainer videos, data visualizations, marketing animations.\n\n"
                "## Installation (if not installed)\n"
                "```\nuv pip install manim\n```\n\n"
                "## Write a Manim script\n"
                "Create a Python file in `<dept>/_wip/` with one or more Scene classes:\n"
                "```python\nfrom manim import *\n\nclass MyScene(Scene):\n"
                "    def construct(self):\n"
                "        text = Text('Hello World')\n"
                "        self.play(Write(text))\n"
                "        self.wait(2)\n"
                "```\n\n"
                "## Render the video\n"
                "```\nmanim render <dept>/_wip/script.py MyScene --format mp4 -o output\n```\n"
                "Output lands in `media/videos/<script>/1080p60/MyScene.mp4` relative to cwd.\n"
                "Copy the final MP4 to `shared/<video-name>.mp4` with file_write or shell cp.\n\n"
                "## Key rules\n"
                "- ALWAYS render with `--format mp4`. Never use default GIF output.\n"
                "- Test with a low-quality flag first: `-ql` (low quality, fast render) to validate.\n"
                "- Full quality: `-qh` (1080p) or `-qm` (720p).\n"
                "- The final MP4 MUST be saved to `shared/` before reporting done.\n"
                "- Cite the exact file path in your report: `shared/<video-name>.mp4`.\n"
                "- Common error: missing `self.wait()` at the end — always add it.\n"
            ),
            required_tools=["shell_exec", "file_write", "file_list"],
        ),
        "video_production": Skill(
            name="Video Production",
            description=(
                "Create full videos with animation, voice narration, and background music. "
                "Uses Manim for animation, Google Cloud TTS for voice, ffmpeg for mixing."
            ),
            instructions=(
                "## Full pipeline overview\n"
                "1. Create animation with Manim → video.mp4\n"
                "2. Generate voice narration with tts_generate → narration.wav\n"
                "3. Download royalty-free music with curl → music.mp3\n"
                "4. Mix everything with ffmpeg → final.mp4\n"
                "5. Save final.mp4 to shared/ and propose youtube_upload\n\n"

                "## Step 1 — Animation with Manim\n"
                "Write a Python script in <dept>/_wip/scene.py:\n"
                "```python\n"
                "from manim import *\n"
                "class MyScene(Scene):\n"
                "    def construct(self):\n"
                "        title = Text('Mon titre').scale(1.5)\n"
                "        self.play(Write(title))\n"
                "        self.wait(2)\n"
                "```\n"
                "Render: `manim render <dept>/_wip/scene.py MyScene --format mp4 -qh`\n"
                "Output: `media/videos/scene/1080p60/MyScene.mp4` (relative to cwd)\n\n"

                "## Step 2 — Voice narration\n"
                "Use tts_generate tool:\n"
                "- text: full narration script (what the voice will say)\n"
                "- output_path: '<dept>/_wip/narration.wav'\n"
                "- voice_name: use settings default or specify (fr-FR-Studio-A for premium)\n"
                "The narration duration determines the video final length.\n\n"

                "## Step 3 — Background music\n"
                "Download a royalty-free track from Pixabay Music (no account needed):\n"
                "```\n"
                "curl -L 'https://cdn.pixabay.com/download/audio/2022/01/18/audio_d0c6ff1bab.mp3'"
                " -o <dept>/_wip/music.mp3\n"
                "```\n"
                "Or generate a simple ambient tone:\n"
                "```\n"
                "ffmpeg -f lavfi -i 'sine=frequency=220:duration=300'"
                " -af 'afade=t=in:d=3,volume=0.3' <dept>/_wip/music.mp3\n"
                "```\n\n"

                "## Step 4 — ffmpeg mix (video + voice + music)\n"
                "```\n"
                "ffmpeg -i <dept>/_wip/video.mp4 \\\n"
                "       -i <dept>/_wip/narration.wav \\\n"
                "       -i <dept>/_wip/music.mp3 \\\n"
                "  -filter_complex \\\n"
                "    '[1:a]volume=1.0[voice];"
                "[2:a]volume=0.20,aloop=loop=-1:size=2e+09[music];"
                "[voice][music]amix=inputs=2:duration=first[audio]' \\\n"
                "  -map 0:v -map '[audio]' \\\n"
                "  -c:v copy -c:a aac -b:a 192k -shortest \\\n"
                "  shared/final.mp4\n"
                "```\n"
                "Key flags:\n"
                "- `volume=0.20` on music = 20% of voice volume\n"
                "- `aloop=loop=-1` = music loops indefinitely\n"
                "- `duration=first` = audio ends when voice ends\n"
                "- `-shortest` = video cut to audio length\n\n"

                "## Step 5 — If no video (voice-only with static image)\n"
                "```\n"
                "ffmpeg -loop 1 -i <dept>/_wip/background.png \\\n"
                "       -i <dept>/_wip/narration.wav \\\n"
                "  -c:v libx264 -tune stillimage -c:a aac \\\n"
                "  -pix_fmt yuv420p -shortest \\\n"
                "  shared/final.mp4\n"
                "```\n\n"

                "## Step 6 — Upload to YouTube\n"
                "```\n"
                "propose_external_action(\n"
                "  action_type='youtube_upload',\n"
                "  recipient='default',\n"
                "  subject='Video title',\n"
                "  content='Video description with hashtags',\n"
                "  file_path='shared/final.mp4',\n"
                "  rationale='...',\n"
                ")\n"
                "```\n\n"

                "## Rules\n"
                "- ALWAYS verify each file exists with file_list before the next step.\n"
                "- Write narration script FIRST, then build the animation to match its duration.\n"
                "- Test with `-ql` (low quality) before final `-qh` render to save time.\n"
                "- If tts_generate fails, check that Cloud Text-to-Speech API is enabled in GCP.\n"
                "- Final MP4 MUST be in shared/ before proposing youtube_upload.\n"
                "- Cite shared/final.mp4 in your report.\n"
            ),
            required_tools=["shell_exec", "tts_generate", "file_write", "file_list", "file_read"],
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
