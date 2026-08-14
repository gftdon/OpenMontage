/**
 * Shared Google Font loads for the Claude CoWork avatar tutorial composition.
 * Loaded once at module scope so every component under src/avatarTutorial/
 * reuses the same font faces — import this file for its side effect.
 *
 * Prompt  = headings + karaoke captions (SemiBold 600, see THEME.type.caption)
 * Sarabun = body copy (THEME.fonts.body)
 * Both need the "thai" subset — the narration and captions are Thai.
 */
import { loadFont as loadPrompt } from "@remotion/google-fonts/Prompt";
import { loadFont as loadSarabun } from "@remotion/google-fonts/Sarabun";

export const promptFont = loadPrompt("normal", {
  weights: ["400", "500", "600", "700"],
  subsets: ["thai", "latin"],
});

export const sarabunFont = loadSarabun("normal", {
  weights: ["400", "500", "700"],
  subsets: ["thai", "latin"],
});

/** Loaded family stacks — equivalent to THEME.fonts.heading / THEME.fonts.body. */
export const HEADING_FONT = promptFont.fontFamily;
export const BODY_FONT = sarabunFont.fontFamily;
