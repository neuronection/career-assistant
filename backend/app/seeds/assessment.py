"""Seeded question bank for phase 2 (standardized scenarios, Phase 23).

Seed-review checklist (admin-enforced): every option set must span >= 3
job families via its interest_keys — no binary either/or questions, no
premature filtering.
"""

BANK_QUESTIONS: list[dict] = [
    {
        "phase": 2,
        "kind": "scenario_mcq",
        "prompt": "A friend asks you to help organize a big local charity event. Which role do you quietly hope for?",
        "help": "Pick the one that feels most like you — there is no wrong answer.",
        "options": [
            {
                "id": "o1",
                "label": "Running the spreadsheet: budget, donors, numbers",
                "detail": "Someone has to keep the money honest.",
                "scores": {
                    "skill_levels": {"organization": 3, "data-analysis": 2},
                    "interest_keys": ["business-finance"],
                },
            },
            {
                "id": "o2",
                "label": "Being on stage with the microphone",
                "detail": "Welcome the crowd, keep the energy up.",
                "scores": {
                    "skill_levels": {"public-speaking": 3},
                    "interest_keys": ["people-teaching", "arts-music"],
                },
            },
            {
                "id": "o3",
                "label": "Designing posters and social posts",
                "detail": "Make the event impossible to ignore.",
                "scores": {
                    "skill_levels": {"visual-design": 3},
                    "interest_keys": ["arts-design"],
                },
            },
            {
                "id": "o4",
                "label": "Setting up tech: sound, streams, website",
                "detail": "If it plugs in, it is yours.",
                "scores": {
                    "skill_levels": {"network-admin": 2, "programming": 2},
                    "interest_keys": ["technology-software"],
                },
            },
        ],
        "sort_index": 1,
    },
    {
        "phase": 2,
        "kind": "scenario_mcq",
        "prompt": "Your class gets a free-form project month. Which project pulls you in first?",
        "audience_stages": ["student"],
        "help": "Imagine zero constraints — which one would you start tonight?",
        "options": [
            {
                "id": "o1",
                "label": "Build an app that solves an everyday annoyance",
                "detail": "From idea to working prototype.",
                "scores": {
                    "skill_levels": {"programming": 3, "problem-solving": 2},
                    "interest_keys": ["technology-software", "technology-ai"],
                },
            },
            {
                "id": "o2",
                "label": "Investigate the school's energy use and propose fixes",
                "detail": "Data collection, analysis, a persuasive report.",
                "scores": {
                    "skill_levels": {"data-analysis": 3, "critical-thinking": 2},
                    "interest_keys": ["science-earth", "business-entrepreneurship"],
                },
            },
            {
                "id": "o3",
                "label": "Film and edit a mini-documentary about the school",
                "detail": "Stories told through a lens.",
                "scores": {
                    "skill_levels": {"video-editing": 3, "storytelling": 2},
                    "interest_keys": ["society-media", "arts-design"],
                },
            },
            {
                "id": "o4",
                "label": "Coach younger students through a tough subject",
                "detail": "Explain it until the lightbulb moment.",
                "scores": {
                    "skill_levels": {"teaching": 3, "empathy": 2},
                    "interest_keys": ["people-teaching", "people-health"],
                },
            },
        ],
        "sort_index": 2,
    },
    {
        "phase": 2,
        "kind": "scenario_mcq",
        "prompt": "Something breaks on a group trip and everyone looks at each other. What happens next, realistically?",
        "help": "Be honest about your reflex, not your ideal self.",
        "options": [
            {
                "id": "o1",
                "label": "You take it apart to see what's wrong",
                "detail": "Mechanical problems yield to patience.",
                "scores": {
                    "skill_levels": {"mechanical-repair": 3, "dexterity": 2},
                    "interest_keys": [
                        "hands-machines",
                        "hands-machines",
                    ],
                },
            },
            {
                "id": "o2",
                "label": "You keep everyone calm and organized",
                "detail": "People panic; you plan.",
                "scores": {
                    "skill_levels": {"leadership": 3, "empathy": 2},
                    "interest_keys": ["people-public-safety", "people-helping"],
                },
            },
            {
                "id": "o3",
                "label": "You negotiate with the rental company for a fix",
                "detail": "Turn on the charm, get it in writing.",
                "scores": {
                    "skill_levels": {"negotiation": 3},
                    "interest_keys": ["business-sales", "people-law-justice"],
                },
            },
        ],
        "sort_index": 3,
    },
    {
        "phase": 2,
        "kind": "scenario_mcq",
        "prompt": "A company offers you a Saturday shadowing one of its teams. Which team do you pick?",
        "audience_stages": ["early_career", "experienced", "switching", "returning"],
        "help": "One Saturday only — choose the team you would learn the most from.",
        "options": [
            {
                "id": "o1",
                "label": "The data team that decides what gets built next",
                "detail": "Dashboards, experiments, evidence.",
                "scores": {
                    "skill_levels": {"data-analysis": 3, "mathematics": 2},
                    "interest_keys": ["technology-data"],
                },
            },
            {
                "id": "o2",
                "label": "The lab team running real experiments",
                "detail": "White coats, pipettes, discoveries.",
                "scores": {
                    "skill_levels": {"lab-techniques": 3, "attention-to-detail": 2},
                    "interest_keys": ["science-chemistry", "science-biology"],
                },
            },
            {
                "id": "o3",
                "label": "The workshop team building the physical product",
                "detail": "CAD models become steel.",
                "scores": {
                    "skill_levels": {"engineering-design": 3},
                    "interest_keys": ["hands-machines", "hands-building"],
                },
            },
            {
                "id": "o4",
                "label": "The care team on the ward",
                "detail": "Where people skills meet medicine.",
                "scores": {
                    "skill_levels": {"empathy": 3, "first-aid": 2},
                    "interest_keys": ["people-health"],
                },
            },
        ],
        "sort_index": 4,
    },
    {
        "phase": 2,
        "kind": "time_allocation",
        "prompt": "A week in your dream job — how would the tasks split?",
        "help": "Give each task a percentage; the total must be exactly 100.",
        "options": [
            {
                "id": "o1",
                "label": "Solving technical problems with tools or code",
                "detail": "Deep, focused building time.",
                "scores": {
                    "skill_levels": {"programming": 4},
                    "interest_keys": ["technology-software"],
                },
            },
            {
                "id": "o2",
                "label": "Working directly with people and their problems",
                "detail": "Conversations, care, coaching.",
                "scores": {
                    "skill_levels": {"empathy": 4},
                    "interest_keys": ["people-health", "people-teaching"],
                },
            },
            {
                "id": "o3",
                "label": "Analysing numbers, patterns and evidence",
                "detail": "Find the signal in the noise.",
                "scores": {
                    "skill_levels": {"data-analysis": 4},
                    "interest_keys": ["technology-data", "technology-data"],
                },
            },
            {
                "id": "o4",
                "label": "Creating things people can see and feel",
                "detail": "Design, film, music, words.",
                "scores": {
                    "skill_levels": {"visual-design": 4},
                    "interest_keys": ["arts-design", "society-media"],
                },
            },
        ],
        "sort_index": 5,
    },
    {
        "phase": 2,
        "kind": "time_allocation",
        "prompt": "You get a free learning year, split across these tracks:",
        "help": "Percentages must sum to 100 — invest in the future you.",
        "options": [
            {
                "id": "o1",
                "label": "How things are built and fixed",
                "detail": "Engines, circuits, structures.",
                "scores": {
                    "skill_levels": {"electronics": 3, "mechanical-repair": 3},
                    "interest_keys": ["hands-machines"],
                },
            },
            {
                "id": "o2",
                "label": "How living things work",
                "detail": "Bodies, animals, plants.",
                "scores": {
                    "skill_levels": {"lab-techniques": 3},
                    "interest_keys": ["science-biology", "nature-animals"],
                },
            },
            {
                "id": "o3",
                "label": "How organisations and markets behave",
                "detail": "Money, persuasion, strategy.",
                "scores": {
                    "skill_levels": {"negotiation": 2, "organization": 2},
                    "interest_keys": ["business-finance", "business-entrepreneurship"],
                },
            },
        ],
        "sort_index": 6,
    },
    {
        "phase": 2,
        "kind": "ranking",
        "prompt": "Rank these workday realities from 'sounds great' to 'no thanks'.",
        "help": "Drag every card once — your top pick carries the most weight.",
        "options": [
            {
                "id": "o1",
                "label": "A quiet desk, a hard problem and headphones",
                "detail": "Deep solo focus all day.",
                "scores": {
                    "skill_levels": {"programming": 2, "critical-thinking": 2},
                    "interest_keys": ["technology-software"],
                },
            },
            {
                "id": "o2",
                "label": "A busy floor where everyone needs you at once",
                "detail": "High energy, high people contact.",
                "scores": {
                    "skill_levels": {"customer-service": 2, "empathy": 2},
                    "interest_keys": ["people-health", "business-sales"],
                },
            },
            {
                "id": "o3",
                "label": "A field site, far from any office",
                "detail": "Weather, machines, real terrain.",
                "scores": {
                    "skill_levels": {"physical-stamina": 2},
                    "interest_keys": ["science-earth", "nature-plants"],
                },
            },
        ],
        "sort_index": 7,
    },
    {
        "phase": 2,
        "kind": "ranking",
        "prompt": "Which compliments would you actually want to earn?",
        "help": "Put the most meaningful one first.",
        "options": [
            {
                "id": "o1",
                "label": "'Your work is flawless — every detail checks out.'",
                "detail": "Precision earns trust.",
                "scores": {
                    "skill_levels": {"attention-to-detail": 3},
                    "interest_keys": ["technology-data", "people-law-justice"],
                },
            },
            {
                "id": "o2",
                "label": "'You explained it so my grandma understood.'",
                "detail": "Clarity is a superpower.",
                "scores": {
                    "skill_levels": {"teaching": 3, "writing": 2},
                    "interest_keys": ["people-teaching", "society-media"],
                },
            },
            {
                "id": "o3",
                "label": "'It shouldn't work, but you made it work.'",
                "detail": "Improvisation and craft.",
                "scores": {
                    "skill_levels": {"problem-solving": 3},
                    "interest_keys": ["technology-robots", "hands-machines"],
                },
            },
        ],
        "sort_index": 8,
    },
]


async def seed_assessment_bank(db) -> int:
    """Insert missing bank questions (idempotent, by prompt)."""
    from sqlalchemy import select

    from app.models.assessment_model import AssessmentQuestion
    from app.models.enums import QuestionSource, QuestionStatus

    existing = {
        prompt
        for prompt in (await db.execute(select(AssessmentQuestion.prompt)))
        .scalars()
        .all()
    }
    added = 0
    for spec in BANK_QUESTIONS:
        if spec["prompt"] in existing:
            continue
        db.add(
            AssessmentQuestion(
                run_id=None,
                phase=spec["phase"],
                kind=spec["kind"],
                prompt=spec["prompt"],
                help=spec.get("help", ""),
                options=spec["options"],
                time_split=spec.get("time_split"),
                source=QuestionSource.BANK.value,
                status=QuestionStatus.ACTIVE.value,
                sort_index=spec.get("sort_index", 0),
                audience_stages=spec.get("audience_stages") or [],
            )
        )
        added += 1
    await db.commit()
    return added
