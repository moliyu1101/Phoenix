type PhoenixLogoProps = {
  size?: number;
  wordmark?: boolean;
  artwork?: boolean;
  decorative?: boolean;
  className?: string;
};

/** The supplied flame phoenix is used unchanged throughout, including compact navigation. */
export function PhoenixLogo({ size = 24, wordmark = false, artwork = false, decorative = false, className = "" }: PhoenixLogoProps) {
  return <span className={`phoenix-logo ${artwork ? "phoenix-logo-artwork" : ""} ${className}`.trim()}
    role={decorative ? undefined : "img"} aria-label={decorative ? undefined : "Phoenix"} aria-hidden={decorative || undefined}>
    {/* Preserve the supplied local artwork bytes and render its icon wrapper directly. */}
    {/* eslint-disable-next-line @next/next/no-img-element */}
    <img src={artwork ? "/brand/phoenix-logo.png" : "/brand/phoenix-mark.svg"}
      width={artwork ? size * 1.5 : size} height={size} alt="" draggable={false}
      className={artwork ? "phoenix-logo-image" : "phoenix-brand-mark"}/>
    {wordmark ? <span className="phoenix-wordmark" aria-hidden="true">Phoenix</span> : null}
  </span>;
}
