"""Controlled vocabularies: interest tags + skill tags (stable keys)."""

INTEREST_TAGS: list[dict] = [
    # science & nature
    {"key": "science-physics", "label": "Physics", "category": "science"},
    {"key": "science-chemistry", "label": "Chemistry", "category": "science"},
    {"key": "science-biology", "label": "Biology", "category": "science"},
    {"key": "science-earth", "label": "Earth & Environment", "category": "science"},
    {"key": "nature-animals", "label": "Animals & Wildlife", "category": "science"},
    {"key": "nature-plants", "label": "Plants & Agriculture", "category": "science"},
    {"key": "science-space", "label": "Space & Astronomy", "category": "science"},
    # technology
    {
        "key": "technology-software",
        "label": "Software & Apps",
        "category": "technology",
    },
    {
        "key": "technology-hardware",
        "label": "Hardware & Electronics",
        "category": "technology",
    },
    {
        "key": "technology-robots",
        "label": "Robotics & Automation",
        "category": "technology",
    },
    {
        "key": "technology-ai",
        "label": "Artificial Intelligence",
        "category": "technology",
    },
    {
        "key": "technology-networks",
        "label": "Networks & Cybersecurity",
        "category": "technology",
    },
    {"key": "technology-games", "label": "Video Games", "category": "technology"},
    {"key": "technology-data", "label": "Data & Statistics", "category": "technology"},
    # people & care
    {"key": "people-teaching", "label": "Teaching & Mentoring", "category": "people"},
    {"key": "people-health", "label": "Health & Care", "category": "people"},
    {"key": "people-helping", "label": "Helping & Social Work", "category": "people"},
    {"key": "people-law-justice", "label": "Law & Justice", "category": "people"},
    {"key": "people-public-safety", "label": "Public Safety", "category": "people"},
    {"key": "people-animals-care", "label": "Animal Care", "category": "people"},
    # business
    {
        "key": "business-entrepreneurship",
        "label": "Entrepreneurship",
        "category": "business",
    },
    {
        "key": "business-marketing",
        "label": "Marketing & Advertising",
        "category": "business",
    },
    {"key": "business-sales", "label": "Sales & Negotiation", "category": "business"},
    {"key": "business-finance", "label": "Finance & Investing", "category": "business"},
    {
        "key": "business-management",
        "label": "Management & Leadership",
        "category": "business",
    },
    {
        "key": "business-logistics",
        "label": "Logistics & Supply Chain",
        "category": "business",
    },
    # arts
    {"key": "arts-visual", "label": "Drawing & Visual Art", "category": "arts"},
    {"key": "arts-design", "label": "Design & Aesthetics", "category": "arts"},
    {"key": "arts-music", "label": "Music & Sound", "category": "arts"},
    {"key": "arts-writing", "label": "Writing & Storytelling", "category": "arts"},
    {"key": "arts-performing", "label": "Performing & Acting", "category": "arts"},
    {"key": "arts-photo-video", "label": "Photography & Video", "category": "arts"},
    # hands-on
    {
        "key": "hands-building",
        "label": "Building & Construction",
        "category": "hands-on",
    },
    {"key": "hands-machines", "label": "Machines & Engines", "category": "hands-on"},
    {
        "key": "hands-electricity",
        "label": "Electricity & Wiring",
        "category": "hands-on",
    },
    {"key": "hands-cooking", "label": "Cooking & Food", "category": "hands-on"},
    {"key": "hands-crafts", "label": "Crafts & Woodwork", "category": "hands-on"},
    {"key": "hands-driving", "label": "Driving & Vehicles", "category": "hands-on"},
    # society
    {"key": "society-history", "label": "History & Culture", "category": "society"},
    {
        "key": "society-languages",
        "label": "Languages & Translation",
        "category": "society",
    },
    {
        "key": "society-politics",
        "label": "Politics & Public Policy",
        "category": "society",
    },
    {
        "key": "society-environment",
        "label": "Environment & Sustainability",
        "category": "society",
    },
    {"key": "society-media", "label": "News & Media", "category": "society"},
    # sports & body
    {"key": "sports-fitness", "label": "Fitness & Training", "category": "sports"},
    {"key": "sports-competition", "label": "Competitive Sports", "category": "sports"},
    {"key": "sports-outdoors", "label": "Outdoor Adventure", "category": "sports"},
]

SKILL_TAGS: list[dict] = [
    {"key": "programming", "label": "Programming", "category": "technical"},
    {"key": "data-analysis", "label": "Data Analysis", "category": "technical"},
    {"key": "mathematics", "label": "Mathematics", "category": "technical"},
    {
        "key": "lab-techniques",
        "label": "Laboratory Techniques",
        "category": "technical",
    },
    {"key": "electronics", "label": "Electronics", "category": "technical"},
    {
        "key": "engineering-design",
        "label": "Engineering Design (CAD)",
        "category": "technical",
    },
    {"key": "mechanical-repair", "label": "Mechanical Repair", "category": "technical"},
    {
        "key": "network-admin",
        "label": "Network Administration",
        "category": "technical",
    },
    {"key": "writing", "label": "Writing", "category": "communication"},
    {"key": "public-speaking", "label": "Public Speaking", "category": "communication"},
    {
        "key": "foreign-languages",
        "label": "Foreign Languages",
        "category": "communication",
    },
    {"key": "negotiation", "label": "Negotiation", "category": "communication"},
    {"key": "teaching", "label": "Teaching & Explaining", "category": "communication"},
    {"key": "empathy", "label": "Empathy & Listening", "category": "interpersonal"},
    {"key": "teamwork", "label": "Teamwork", "category": "interpersonal"},
    {"key": "leadership", "label": "Leadership", "category": "interpersonal"},
    {
        "key": "conflict-resolution",
        "label": "Conflict Resolution",
        "category": "interpersonal",
    },
    {
        "key": "customer-service",
        "label": "Customer Service",
        "category": "interpersonal",
    },
    {"key": "visual-design", "label": "Visual Design", "category": "creative"},
    {"key": "storytelling", "label": "Storytelling", "category": "creative"},
    {"key": "music-performance", "label": "Music Performance", "category": "creative"},
    {"key": "video-editing", "label": "Video Editing", "category": "creative"},
    {"key": "cooking", "label": "Cooking", "category": "creative"},
    {"key": "critical-thinking", "label": "Critical Thinking", "category": "cognitive"},
    {"key": "problem-solving", "label": "Problem Solving", "category": "cognitive"},
    {
        "key": "attention-to-detail",
        "label": "Attention to Detail",
        "category": "cognitive",
    },
    {"key": "memory-accuracy", "label": "Memory & Accuracy", "category": "cognitive"},
    {
        "key": "organization",
        "label": "Organization & Planning",
        "category": "cognitive",
    },
    {"key": "physical-stamina", "label": "Physical Stamina", "category": "physical"},
    {"key": "dexterity", "label": "Manual Dexterity", "category": "physical"},
    {"key": "driving", "label": "Driving", "category": "physical"},
    {"key": "first-aid", "label": "First Aid", "category": "physical"},
]
