// Web clips and rects interface for Youtube-YT-News-Style01-V2 format
export interface WebRect { x: number; y: number; w: number; h: number; text?: string }
export const WEB_CLIPS: Record<string, { y: number; h: number }> = {};
export const WEB_RECTS: Record<string, WebRect> = {};
