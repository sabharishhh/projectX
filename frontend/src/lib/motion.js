import { cubicOut } from 'svelte/easing';

const reduced = () =>
  typeof window !== 'undefined' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches;

export const dur = (ms) => (reduced() ? 0 : ms);

export const settings = { fast: 160, base: 240, slow: 380, ease: cubicOut };

/** Slide + fade, for panel and disclosure content. */
export function reveal(node, { duration = settings.base, y = -4 } = {}) {
  return {
    duration: dur(duration),
    easing: settings.ease,
    css: (t) => `opacity:${t}; transform:translateY(${(1 - t) * y}px)`
  };
}

/** Draws attention once, without looping. Used when a conflict appears. */
export function arrive(node, { duration = settings.slow } = {}) {
  return {
    duration: dur(duration),
    easing: settings.ease,
    css: (t) => `opacity:${t}; transform:scale(${0.98 + t * 0.02})`
  };
}