// Single source of truth for style-specific naming and tone copy.
// Used by Home, Style picker, Dispatch — anywhere we surface the handler or
// organization to the user.

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

export function styleMeta(style) {
  return STYLE_META[style] || STYLE_META.agency;
}
