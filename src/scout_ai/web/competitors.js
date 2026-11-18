// Positioning research per competitor, from README §3 (public research, not collected data).
// Fields left null were not researched: the battlecard says so instead of guessing.
// "angles" are hypotheses for Marketing to test, derived from the same research.

export const DIMENSIONS = [
  ["origin", "Origin"],
  ["model", "Model"],
  ["segments", "Strong segments"],
  ["brazil", "Brazil presence"],
  ["message", "Core message"],
  ["weakness", "Exploitable weakness"],
];

export const MYLIMS = {
  origin: "Labsoft, Jundiaí, Brazil (2002); part of Confience (STG group) since June 2025",
  model: "Cloud LIMS",
  segments: "Food, agribusiness, environmental, industrial, Latam",
  brazil: "Strong, local team",
  message: "Usability, Latam leadership, global ambition",
  weakness: "Confience brand still new after the acquisition",
};

// Keyed by the fictional names the API answers with (scout_ai/aliases.py). Details that
// would identify the real company (founding year, owners, product names, links) are left out.
export const PROFILES = {
  "Kestrel LIMS": {
    origin: "USA, decades in the market",
    model: "Enterprise, highly configurable",
    segments: "Pharma, government, regulated manufacturing",
    brazil: "Through integrators",
    message: "Functional depth and compliance",
    weakness: "Complex, costly implementation",
    why: "The global enterprise benchmark, strong in highly regulated environments. This is who we win or lose large accounts against.",
    angles: [
      "Lead with usability and a cloud model against a heavy, costly enterprise implementation.",
      "In Brazil, contrast our local team with delivery through integrators.",
    ],
  },
  "Orbis LIMS": {
    origin: "Owned by private equity",
    model: null,
    segments: "Regulated clinical and pharma labs",
    brazil: null,
    message: null,
    weakness: null,
    why: "It shows up in HubSpot deals, and Confience already runs a comparison page against it: an active campaign target.",
    angles: ["Keep our comparison page fed with proof points from deals we win against it."],
  },
  "Meridian Lab Systems": {
    origin: "UK/USA; a portfolio built from acquisitions",
    model: "Laboratory platform (LIS + LIMS)",
    segments: "Clinical/diagnostics, environmental, public health, agriculture",
    brazil: "To be confirmed",
    message: "Scale and portfolio breadth",
    weakness: "Integrating many acquired products",
    why: "Its environmental LIMS covers environmental, water quality, public health and agriculture labs: direct overlap with myLIMS segments. Not in HubSpot deals yet.",
    angles: [
      "Position one product built for food, agro and environmental labs against a portfolio assembled from acquisitions.",
      "Watch HubSpot for the first deal against it.",
    ],
  },
  "Halcyon LIMS": {
    origin: "USA, decades in the market",
    model: "Integrated platform (LIMS + ELN + data), cloud-oriented",
    segments: "Life sciences, pharma",
    brazil: "Growing (local acquisitions, partner)",
    message: "Integrated, award-winning platform",
    weakness: "Lower public review rating, few reviews",
    why: "The most active competitor in our home market (local acquisitions and a Brazilian sales partner), but its site blocks automated collection, so it stays on the watchlist.",
    angles: [
      "Defend Brazil and Latam with local customer stories and a team in the market since 2002.",
      "Lean on reviews and references, where its public rating is weaker.",
    ],
  },
  "Nimbus LIMS": {
    origin: null,
    model: "Low-cost SaaS, per-user pricing",
    segments: "Small labs (2–50 people)",
    brazil: null,
    message: null,
    weakness: null,
    why: "A threat in the entry-level segment, not in enterprise accounts.",
    angles: ["Answer on value and room to grow for small labs, not on price."],
  },
};
