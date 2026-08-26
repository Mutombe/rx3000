import type { SVGProps } from "react";

/** The Claude starburst.
 *
 *  Used everywhere an AI capability appears, because the assistant behind it is
 *  Claude and saying so is more honest than a generic sparkle. A sparkle is the
 *  icon every product uses for "magic happens here"; this is a mark that names
 *  what is actually answering, which is the tone a pharmacy system wants.
 *
 *  Inherits `currentColor`, so callers control the colour, and is sized like a
 *  Phosphor icon (1em square by default) so it drops in beside the rest of the
 *  set without special casing.
 */
export default function ClaudeIcon({
  size,
  // Accepted and ignored so this drops into the same slots as a Phosphor icon.
  // The mark is solid; there is no outline variant of it to switch to.
  weight: _weight,
  ...props
}: SVGProps<SVGSVGElement> & { size?: number | string; weight?: string }) {
  // Twelve tapered rays of alternating length around the centre. The uneven
  // lengths are the point: a perfectly regular star reads as a generic asterisk.
  const rays = [
    { angle: 0, length: 10 },
    { angle: 30, length: 7.2 },
    { angle: 60, length: 9.4 },
    { angle: 90, length: 7.0 },
    { angle: 120, length: 9.8 },
    { angle: 150, length: 7.4 },
    { angle: 180, length: 10 },
    { angle: 210, length: 7.1 },
    { angle: 240, length: 9.5 },
    { angle: 270, length: 7.3 },
    { angle: 300, length: 9.7 },
    { angle: 330, length: 7.2 },
  ];
  return (
    <svg
      viewBox="0 0 24 24"
      width={size ?? "1em"}
      height={size ?? "1em"}
      fill="currentColor"
      aria-hidden="true"
      {...props}
    >
      {rays.map((ray) => (
        <path
          key={ray.angle}
          d={`M 12 12 L ${12 - 1.05} ${12 - ray.length} Q 12 ${12 - ray.length - 1.1} ${12 + 1.05} ${12 - ray.length} Z`}
          transform={`rotate(${ray.angle} 12 12)`}
        />
      ))}
      <circle cx="12" cy="12" r="2.1" />
    </svg>
  );
}
