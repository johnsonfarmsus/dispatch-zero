// Single source of truth for style-specific naming and tone copy.
// Used by Home, Style picker, Dispatch — anywhere we surface the handler or
// organization to the user.

// Rank names by adventure style. Index = rank integer (0..10) returned by
// the backend's services.rank.completions_to_rank. Keep length aligned to
// MAX_RANK + 1 in the backend.
const RANKS = {
  pulp: [
    "Volunteer",
    "Junior Cataloguer",
    "Cataloguer",
    "Senior Cataloguer",
    "Junior Curator",
    "Curator",
    "Senior Curator",
    "Junior Expeditioner",
    "Expeditioner",
    "Senior Expeditioner",
    "Antiquarian",
  ],
  agency: [
    "Intern",
    "Junior Analyst",
    "Analyst",
    "Field Analyst",
    "Junior Operative",
    "Operative",
    "Field Operative",
    "Junior Specialist",
    "Specialist",
    "Field Specialist",
    "Officer",
  ],
  guild: [
    "Aspirant",
    "Initiate",
    "Sworn",
    "Acolyte",
    "Junior Warden",
    "Warden",
    "Senior Warden",
    "Junior Keeper",
    "Keeper",
    "Senior Keeper",
    "Magister",
  ],
};

export const STYLE_META = {
  pulp: {
    handler: "Professor Zero",
    org: "The Archive",
    tone:
      "Globe-trotting, relic-hunting, expedition energy. Warm and curious — " +
      "occasionally reckless. Briefings read like field notes from a colleague " +
      "who's about to ask you for an unreasonable favor.",
  },
  agency: {
    handler: "Director Zero",
    org: "The Agency",
    tone:
      "Cold, controlled, professional. Vaguely threatening. Briefings read " +
      "like declassified directives. The Agency's purpose is never fully " +
      "explained, and you don't ask.",
  },
  guild: {
    handler: "Guildmaster Zero",
    org: "The Guild",
    tone:
      "Ancient and formal. Briefings feel ceremonial and faintly unsettling — " +
      "as though they have been performed many times before, by other agents " +
      "whose names are no longer spoken.",
  },
};

// Short, viewport-friendly taglines per org. The longer prose lives in
// STYLE_META.tone; these stay terse for the selectable org cards on both the
// Settings (style picker) and Signup screens — single source of truth so the
// two screens can't drift.
export const TAGLINES = {
  pulp: "Warm, curious, expedition energy.",
  agency: "Cold, classified, professional.",
  guild: "Ancient, ceremonial, formal.",
};

// Per-org accent colors. Mirrors the body[data-style="..."] --accent values
// in tokens.css. Used where we need an org's color BEFORE the body's
// data-style is set (e.g. the signup org picker, where every card would
// otherwise inherit the default agency teal via var(--accent)).
export const ACCENTS = {
  pulp: "#d68a3c",
  agency: "#4ec5d6",
  guild: "#a472d6",
};

export function styleMeta(style) {
  return STYLE_META[style] || STYLE_META.agency;
}

export function rankName(style, rank) {
  const list = RANKS[style] || RANKS.agency;
  const i = Math.max(0, Math.min(rank ?? 0, list.length - 1));
  return list[i];
}
