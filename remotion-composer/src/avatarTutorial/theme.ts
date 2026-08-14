/**
 * Design tokens for the Claude CoWork avatar tutorial composition.
 * Single source of truth — every component in src/avatarTutorial/ imports from here.
 * Mirrors projects/claude-cowork-avatar-tutorial/artifacts/edit_decisions.json.
 */
export const THEME = {
  canvas: { width: 1080, height: 1920, fps: 30, durationFrames: 2729 },

  colors: {
    bgTop: '#1A1519',
    bgBottom: '#241B20',
    glowCoral: 'rgba(216, 119, 87, 0.16)',
    card: '#141116',
    cardBorder: 'rgba(255,255,255,0.07)',
    mediaBg: '#0D0B0F',
    text: '#F7F2EC',
    textDim: '#B8ACA4',
    accent: '#E8836B', // Claude coral
    accentDeep: '#D97757',
    highlight: '#FFC53D', // active caption phrase
    chipText: '#FFFFFF',
    chipNeutral: 'rgba(255,255,255,0.10)',
    progressTrack: 'rgba(255,255,255,0.08)',
  },

  layout: {
    card: { x: 48, y: 72, w: 984, h: 1016, radius: 32 },
    header: { x: 80, y: 112, h: 64 },
    media: { x: 80, y: 196, w: 920, h: 620, radius: 20 },
    captionBand: { x: 80, y: 852, w: 920, h: 168 },
    dividerY: 1152,
    avatar: { x: 0, y: 1152, w: 1080, h: 768 },
    progress: { x: 48, y: 36, w: 984, h: 6 },
  },

  fonts: {
    heading: "'Prompt', sans-serif", // Google font, Thai-capable, geometric
    body: "'Sarabun', sans-serif", // Google font, Thai-capable, readable
  },

  type: {
    chip: { fontSize: 26, fontWeight: 700, letterSpacing: 1 },
    cardTitle: { fontSize: 56, fontWeight: 700 },
    cardBody: { fontSize: 38, fontWeight: 500 },
    cardSub: { fontSize: 30, fontWeight: 400 },
    caption: { fontSize: 48, fontWeight: 600 },
  },

  motion: {
    popFrames: 6, // caption pop-in
    cardEnterFrames: 12, // motion card element stagger base
    spring: { damping: 14, stiffness: 160, mass: 0.6 },
  },

  shadows: {
    card: '0 24px 60px rgba(0,0,0,0.45)',
    media: '0 8px 24px rgba(0,0,0,0.35)',
    chip: '0 4px 12px rgba(0,0,0,0.30)',
  },
} as const;

export type Theme = typeof THEME;
