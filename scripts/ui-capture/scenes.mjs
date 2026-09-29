/**
 * UI capture scene catalog for Career Assistant (repo-owned; the
 * family-standard sync script never overwrites this file).
 *
 * Captures run against a demo instance (synthetic personas, mock AI —
 * see docs/dev/visual-tour.md for the boot recipe). waitForSelectors use
 * the app's data-testid anchors.
 *
 * Chat scenes drive the mock provider's demo scripts / ops path on
 * purpose: prompts are chosen so answers carry rendered items — job
 * reference chips and HITL proposal cards, not just prose.
 */
// NOTE: scenes for pages that are hidden behind dev mode (beta) are kept
// here commented out — Autopilot, Postings (+detail), Interviews, Growth.
// They re-enable by uncommenting when those pages leave beta.
export const groups = [
  "Authentication",
  "Overview",
  "Career exploration",
  "Working life",
  "Your profile",
  "AI assistant",
  "Settings",
];

export const scenes = [
  {
    name: "login",
    group: "Authentication",
    caption: "Sign-in screen — cookie-session auth with CSRF double-submit.",
    narration: "Sign in — your career workspace remembers everything you feed it.",
    path: "/",
    auth: false,
    fullPage: false,
    viewports: ["desktop"],
    waitForSelector: "form",
  },
  {
    name: "dashboard",
    group: "Overview",
    caption: "Dashboard — career state at a glance with the docked chat.",
    narration: "The dashboard shows your top matches, fresh postings and applications — with the assistant always one click away.",
    path: "/",
    viewports: ["desktop"],
    waitForSelector: "[data-testid='dashboard']",
  },
  {
    name: "onboarding",
    group: "Overview",
    caption: "Onboarding wizard — guided or express start paths.",
    narration: "Onboarding gets you to a useful profile in minutes — guided, or express if you already have a CV.",
    path: "/onboarding",
    viewports: ["desktop"],
    waitForSelector: "[data-testid='onboarding']",
  },
  {
    name: "catalog",
    group: "Career exploration",
    caption: "Job family catalog — the taxonomy tree with AI generation.",
    narration: "The catalog maps the world of jobs into families and skills — extendable with AI.",
    path: "/catalog",
    viewports: ["desktop"],
    waitForSelector: "[data-testid='catalog']",
  },
  {
    name: "rankings",
    group: "Career exploration",
    caption: "Matched rankings — fit scores with the compare tray.",
    narration: "Rankings score every role against your profile — compare the shortlist side by side.",
    path: "/rankings",
    viewports: ["desktop"],
    waitForSelector: "[data-testid='rankings']",
  },
  {
    name: "job-detail",
    group: "Career exploration",
    caption: "Job insights — fit score, AI explanations, skill gaps and university paths for Data Scientist.",
    narration: "Open a role and the insights panel explains the fit — strengths, gaps, prerequisites and the paths that close them.",
    path: "/jobs/data-scientist",
    interactions: [
      { action: "waitFor", selector: "[data-testid='job-score-card']", timeout: 15000 },
      { action: "wait", ms: 2000 },
    ],
    viewports: ["desktop"],
    waitForSelector: "[data-testid='job-detail']",
  },
  /* ——— BETA (hidden in dev mode) — re-enable when the page ships ———
  {
    name: "postings",
    group: "Career exploration",
    caption: "Live postings feed from connected sources.",
    narration: "Live postings arrive from connected boards, deduplicated and linked to catalog roles.",
    path: "/postings",
    viewports: ["desktop"],
    waitForSelector: "[data-testid='postings-page']",
  },
  ——————————————————————————————————————————————————————————————— */
  /* ——— BETA (hidden in dev mode) — re-enable when the page ships ———
  {
    name: "posting-detail",
    group: "Career exploration",
    caption: "Posting detail — extracted skills, provenance and fit for a seeded demo posting.",
    narration: "Every posting is parsed: extracted skills, provenance and how it fits you.",
    path: "/postings?posting=DE000001",
    viewports: ["desktop"],
    waitForSelector: "[data-testid='posting-detail']",
  },
  ——————————————————————————————————————————————————————————————— */
  {
    name: "universities",
    group: "Career exploration",
    caption: "Universities and pathways — funding, deadlines and degree-to-job routes.",
    narration: "And when a role needs study first — universities, deadlines and funding, mapped to the job.",
    path: "/catalog/universities",
    viewports: ["desktop"],
    waitForSelector: "[data-testid='universities']",
  },
  /* ——— BETA (hidden in dev mode) — re-enable when the page ships ———
  {
    name: "autopilot",
    group: "Working life",
    caption: "Career Autopilot — goal-driven agent searches with budgets.",
    narration: "Career Autopilot runs goal-driven searches in the background — with budgets and explainable shortlists.",
    path: "/autopilot",
    viewports: ["desktop"],
    waitForSelector: "[data-testid='autopilot-page']",
  },
  ——————————————————————————————————————————————————————————————— */
  /* ——— BETA (hidden in dev mode) — re-enable when the page ships ———
  {
    name: "interviews",
    group: "Working life",
    caption: "Interview prep — posting-grounded mock interviews.",
    narration: "Interview prep runs mock interviews grounded in the actual posting.",
    path: "/interviews",
    viewports: ["desktop"],
    waitForSelector: "[data-testid='interviews-page']",
  },
  ——————————————————————————————————————————————————————————————— */
  /* ——— BETA (hidden in dev mode) — re-enable when the page ships ———
  {
    name: "growth",
    group: "Working life",
    caption: "Growth toolkit — roadmaps, radar and check-ins.",
    narration: "The growth toolkit keeps the long game visible — roadmaps, near-miss radar and check-ins.",
    path: "/growth",
    viewports: ["desktop"],
    waitForSelector: "[data-testid='growth']",
  },
  ——————————————————————————————————————————————————————————————— */
  {
    name: "profile-experience",
    group: "Your profile",
    caption: "Experience timeline — quantified achievements from the seeded demo persona.",
    narration: "Your profile holds structured experience — quantified achievements the matching engine can actually read.",
    path: "/profile/experience",
    viewports: ["desktop"],
    waitForSelector: "[data-testid='experience-page']",
  },
  {
    name: "cv-studio",
    group: "Working life",
    caption: "CV Studio — three routes to a CV, versions and exports, with rendered page thumbnails.",
    narration: "CV Studio builds your CV three ways — from your profile, from an import, or with AI variants.",
    path: "/cv",
    interactions: [
      { action: "waitFor", selector: "[data-testid='cv-card-thumbnail'][data-thumbnail-state='ready']", timeout: 20000 },
    ],
    viewports: ["desktop"],
    waitForSelector: "[data-testid='cv-studio']",
  },
  {
    name: "cv-builder",
    group: "Working life",
    caption: "CV builder — live preview of a modern sidebar CV (profile, skills and languages in the sidepanel) with version history.",
    narration: "The builder shows the live page as you edit — modern sidebar template, version history, one-click export.",
    path: "/cv/{cvId}",
    interactions: [
      { action: "waitFor", selector: "[data-testid='builder-inspector']", timeout: 15000 },
      { action: "wait", ms: 5000 },
    ],
    viewports: ["desktop"],
    waitForSelector: "[data-testid='cv-builder']",
  },
  {
    name: "chat",
    group: "AI assistant",
    caption: "Assistant chat — role-fit answer with job reference chips (mock AI on the demo instance).",
    narration: "Ask which roles fit you — the answer is grounded in your profile and links straight to the roles.",
    path: "/chat",
    interactions: [
      { action: "fill", selector: "[data-as='chat-composer'] textarea", value: "Which roles fit my profile best?" },
      { action: "press", key: "Enter" },
      { action: "wait", ms: 3000 },
    ],
    viewports: ["desktop"],
    waitForSelector: "[data-as='chat-composer'] textarea",
  },
  {
    name: "chat-proposals",
    group: "AI assistant",
    caption: "HITL proposals — the assistant drafts profile edits as review cards with before/after previews.",
    narration: "Ask for an edit and nothing happens silently — the change arrives as a review card you approve or reject.",
    path: "/chat",
    interactions: [
      { action: "fill", selector: "[data-as='chat-composer'] textarea", value: "Expand my first experience description with the stock-count automation result" },
      { action: "press", key: "Enter" },
      { action: "wait", ms: 5000 },
    ],
    viewports: ["desktop"],
    waitForSelector: "[data-testid^='hitl-card-']",
  },
  {
    name: "settings-account",
    group: "Settings",
    caption: "Settings — account pane of the settings shell.",
    narration: "And everything stays yours — settings, export and account controls included.",
    path: "/settings/account",
    viewports: ["desktop"],
    waitForSelector: "[data-testid='settings-account']",
  },
];
