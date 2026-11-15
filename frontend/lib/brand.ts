/** Phoenix brand metadata shared by the UI, install icons and the palette engine. */
export const BRAND_VERSION = "phoenix-0.2.2";

export type BrandColors = { accent: string; ink: string; surface: string };
export const DEFAULT_BRAND_COLORS: BrandColors = {
  accent: "#87a7ff",
  ink: "#0b0e12",
  surface: "#0f1011",
};

function hexColor(value: string | null | undefined, fallback: string): string {
  const hex = value?.replace(/^#/, "");
  return hex && /^[\da-f]{6}$/i.test(hex) ? `#${hex.toLowerCase()}` : fallback;
}

export function brandColorsFromParams(params: URLSearchParams): BrandColors {
  return {
    accent: hexColor(params.get("accent"), DEFAULT_BRAND_COLORS.accent),
    ink: hexColor(params.get("ink"), DEFAULT_BRAND_COLORS.ink),
    surface: hexColor(params.get("surface"), DEFAULT_BRAND_COLORS.surface),
  };
}

export function brandAssetParams(colors: BrandColors): URLSearchParams {
  return new URLSearchParams({
    v: BRAND_VERSION,
    accent: hexColor(colors.accent, DEFAULT_BRAND_COLORS.accent).slice(1),
    ink: hexColor(colors.ink, DEFAULT_BRAND_COLORS.ink).slice(1),
    surface: hexColor(colors.surface, DEFAULT_BRAND_COLORS.surface).slice(1),
  });
}

/** Static install artwork derived from the supplied Phoenix logo. */
export function brandIconUrl(_colors: BrandColors, size: 180 | 192 | 512): string {
  if (size === 512) return "/favicon.svg";
  if (size === 180) return "/brand/phoenix-logo.png";
  return "/favicon.svg";
}

/** Keep the stable head links pointed at the Phoenix artwork as the theme changes. */
export function updateBrandHead(_palette: Record<string, string>): void {
  void _palette;
  if (typeof document === "undefined") return;
  const favicon = document.getElementById("phoenix-favicon");
  const apple = document.getElementById("phoenix-apple-icon");
  const manifest = document.getElementById("phoenix-manifest");
  favicon?.setAttribute("href", "/favicon.svg");
  apple?.setAttribute("href", "/brand/phoenix-logo.png");
  manifest?.setAttribute("href", "/manifest.json");
}
