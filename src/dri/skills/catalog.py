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
                "Create cinematic videos with real footage, animation, voice narration, and music. "
                "Full pipeline: source clips (yt-dlp) → Manim animation → TTS narration → "
                "generated music (ffmpeg) → multi-segment assembly → YouTube upload."
            ),
            instructions=(
                "## Pipeline overview\n"
                "A production video is assembled from segments. Each segment is one of:\n"
                "- A text card (dark background + text, generated with ffmpeg drawtext)\n"
                "- A real footage clip (extracted from YouTube with yt-dlp)\n"
                "- A Manim animation (rendered with manim)\n"
                "All segments share the same format (1920x1080, 60fps, libx264, aac 192k).\n"
                "Final step: concat all segments → upload to YouTube as unlisted.\n\n"

                "## Step 1 — Extract real footage clips\n"
                "```\n"
                "# Download full video first (best quality ≤1080p)\n"
                "yt-dlp -f 'bestvideo[height<=1080]+bestaudio/best' "
                "-o <dept>/_wip/source.%(ext)s <youtube_url>\n\n"
                "# Cut a specific timestamp range (no re-encode, instant)\n"
                "ffmpeg -ss 00:37:41 -to 00:38:08 -i <dept>/_wip/source.mp4 "
                "-c copy <dept>/_wip/clip_a.mp4\n"
                "```\n"
                "Always verify the cut visually: check duration with ffprobe.\n\n"

                "## Step 2 — Create text cards\n"
                "```\n"
                "ffmpeg -y -f lavfi -i color=c=0x0A0E1A:size=1920x1080:rate=60 \\\n"
                "  -vf \"drawtext=text='MAIN TEXT':fontcolor=#F0F4FF:fontsize=72:"
                "x=(w-text_w)/2:y=(h-text_h)/2-40,"
                "drawtext=text='Subtitle':fontcolor=#4A9EFF:fontsize=26:"
                "x=(w-text_w)/2:y=(h+text_h)/2+10\" \\\n"
                "  -t 4 -c:v libx264 -preset fast -crf 18 -pix_fmt yuv420p -an "
                "<dept>/_wip/card.mp4\n"
                "```\n"
                "Use dark background #0A0E1A, white text #F0F4FF, accent #4A9EFF.\n\n"

                "## Step 3 — Manim animation\n"
                "```python\n"
                "from manim import *\n"
                "class MyScene(Scene):\n"
                "    def construct(self):\n"
                "        title = Text('Titre').scale(1.5)\n"
                "        self.play(Write(title))\n"
                "        self.wait(2)\n"
                "```\n"
                "Render: `manim render <dept>/_wip/scene.py MyScene --format mp4 -qh`\n"
                "Output: `media/videos/scene/1080p60/MyScene.mp4` (relative to cwd).\n"
                "Test first with `-ql` flag (fast, low quality).\n\n"

                "## Step 4 — TTS narration\n"
                "Use tts_generate tool:\n"
                "- output_path: '<dept>/_wip/narration.wav'\n"
                "- voice_name: 'fr-FR-Studio-D' (male premium) or 'fr-FR-Studio-A' (female)\n"
                "- speaking_rate: 0.93 for natural pace\n"
                "Multiple narrations can be concatenated:\n"
                "```\n"
                "ffmpeg -i narr1.wav -i narr2.wav "
                "-filter_complex '[0:a][1:a]concat=n=2:v=0:a=1[a]' -map '[a]' combined.wav\n"
                "```\n\n"

                "## Step 5 — Generate background music\n"
                "Use ffmpeg aevalsrc to generate cinematic chord pads (no external download needed):\n"
                "```\n"
                "# Ambient Dm7 (mysterious) — 60s\n"
                "ffmpeg -y -f lavfi \\\n"
                "  -i \"aevalsrc=0.35*sin(2*PI*146.8*t)+0.28*sin(2*PI*174.6*t)"
                "+0.22*sin(2*PI*220*t):c=stereo:s=44100\" \\\n"
                "  -t 60 -af \"afade=t=in:st=0:d=2,afade=t=out:st=57:d=3,"
                "aecho=0.8:0.7:60:0.4\" \\\n"
                "  -codec:a libmp3lame -q:a 3 music_ambient.mp3\n"
                "```\n"
                "Chord frequencies: Dm7=[146.8,174.6,220,261.6] | "
                "Gmaj7=[196,246.9,293.7,370] | Cmaj7=[261.6,329.6,392,493.9]\n\n"

                "## Step 6 — Build segments (video + audio mix)\n"
                "Three patterns:\n"
                "```\n"
                "# Pattern A: clip with original audio + music underneath\n"
                "ffmpeg -i clip.mp4 -ss <offset> -i music.mp3 \\\n"
                "  -filter_complex '[0:a]volume=1.0[orig];[1:a]volume=0.14[music];"
                "[orig][music]amix=inputs=2:duration=first[a]' \\\n"
                "  -map 0:v -map '[a]' -c:v libx264 -c:a aac -b:a 192k -pix_fmt yuv420p seg.mp4\n\n"
                "# Pattern B: silent video + music only\n"
                "ffmpeg -i card.mp4 -ss <offset> -i music.mp3 \\\n"
                "  -filter_complex '[1:a]volume=0.35[a]' \\\n"
                "  -map 0:v -map '[a]' -c:v libx264 -c:a aac -b:a 192k "
                "-pix_fmt yuv420p -t <duration> seg.mp4\n\n"
                "# Pattern C: silent video + narration + music\n"
                "ffmpeg -i video.mp4 -i narration.wav -ss <offset> -i music.mp3 \\\n"
                "  -filter_complex '[1:a]volume=1.0[narr];[2:a]volume=0.18[music];"
                "[narr][music]amix=inputs=2:duration=first[a]' \\\n"
                "  -map 0:v -map '[a]' -c:v libx264 -c:a aac -b:a 192k "
                "-pix_fmt yuv420p -shortest seg.mp4\n"
                "```\n\n"

                "## Step 7 — Normalize and concatenate all segments\n"
                "```\n"
                "# Normalize each segment to same format\n"
                "ffmpeg -i seg01.mp4 \\\n"
                "  -vf 'scale=1920:1080:force_original_aspect_ratio=decrease,"
                "pad=1920:1080:(ow-iw)/2:(oh-ih)/2' \\\n"
                "  -r 60 -c:v libx264 -c:a aac -b:a 192k -ar 44100 -ac 2 "
                "-pix_fmt yuv420p seg01_n.mp4\n\n"
                "# Write concat list and merge\n"
                "# concat_list.txt: one 'file seg01_n.mp4' per line\n"
                "ffmpeg -f concat -safe 0 -i concat_list.txt \\\n"
                "  -c:v libx264 -c:a aac -b:a 192k -pix_fmt yuv420p shared/final.mp4\n"
                "```\n\n"

                "## Step 8 — Upload to YouTube\n"
                "```\n"
                "propose_external_action(\n"
                "  action_type='youtube_upload',\n"
                "  recipient='default',\n"
                "  subject='Video title',\n"
                "  content='Full description with links and hashtags',\n"
                "  file_path='shared/final.mp4',\n"
                "  privacy_status='unlisted',\n"
                "  rationale='...',\n"
                ")\n"
                "```\n"
                "Always use privacy_status='unlisted' unless the founder explicitly asks for 'public'.\n\n"

                "## Rules\n"
                "- Plan the full segment list FIRST (timings, content, which pattern) before any shell call.\n"
                "- ALWAYS verify each file exists with file_list before the next step.\n"
                "- Narration script goes first — animation and segment durations adapt to it.\n"
                "- All intermediate files in <dept>/_wip/. Only shared/final.mp4 is the deliverable.\n"
                "- Use ffprobe to check duration of any file you didn't generate yourself.\n"
                "- If yt-dlp fails on a URL, it may be geo-blocked — report to manager and skip that clip.\n"
            ),
            required_tools=["shell_exec", "tts_generate", "file_write", "file_list", "file_read"],
        ),
        # ── Outreach ─────────────────────────────────────────
        "cold_outreach": Skill(
            name="Cold Outreach",
            description=(
                "Write high-impact cold emails and messages for outreach to founders, investors, "
                "and decision-makers. Follows proven frameworks for brevity and directness."
            ),
            instructions=(
                "## Core rules (non-negotiable)\n"
                "1. **Be Brief** — the message must be understandable in 10 seconds.\n"
                "2. **No bullshit** — no flattery, no buzzwords, no vague promises. Facts only.\n"
                "3. **The Ask** — state exactly what you want. Stage? Investment? Advice? Meeting? "
                "Be specific: role, dates, context.\n"
                "4. **The Story** — why this person, why now. One concrete fact that makes them care.\n\n"

                "## Structure\n"
                "Subject: the single most compelling fact (not a question, not a tease).\n"
                "Body (4-6 lines max):\n"
                "  Line 1-2: The story / proof — what was built or done, with a concrete detail.\n"
                "  Line 3: The ask — specific, dated, actionable.\n"
                "  Line 4: One or two links (code, video, portfolio) — framed as optional proof.\n"
                "Sign with first name only.\n\n"

                "## What to avoid\n"
                "- 'I've been following your work for years' → delete\n"
                "- 'I'm passionate about...' → delete\n"
                "- 'I would be honored to...' → delete\n"
                "- Any sentence the recipient didn't ask for\n"
                "- School name and grades (irrelevant to most decision-makers)\n\n"

                "## Proven subject line patterns\n"
                "- 'J'ai construit [X] que tu as décrit' (proof of execution)\n"
                "- '[Action] en [timeframe] — [ask]' (speed + specificity)\n"
                "- '[Specific result] — [ask]' (result-first)\n\n"

                "## Profile differentiation (show, don't tell)\n"
                "An unusual profile is conveyed through actions, not adjectives.\n"
                "Instead of 'I'm different' → state what you built, alone, in how long.\n"
                "Speed of execution + working proof = profile.\n\n"

                "## After writing\n"
                "Use propose_external_action(action_type='email') to queue for founder approval.\n"
                "Subject → action.subject, body → action.content, recipient → action.recipient.\n"
            ),
            required_tools=[],
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
