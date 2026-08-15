import type { ReactNode } from "react";

type IconProps = { className?: string };

function Svg({ className, children }: IconProps & { children: ReactNode }) {
  return (
    <svg
      className={className}
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

export function IconReview({ className }: IconProps) {
  return (
    <Svg className={className}>
      <path d="M3 3.5h6.5L13 7v5.5H3z" />
      <path d="M9.5 3.5V7H13" />
      <path d="M5.5 9.5h5M5.5 11.5h3.5" />
    </Svg>
  );
}

export function IconArchitecture({ className }: IconProps) {
  return (
    <Svg className={className}>
      <rect x="2.5" y="2.5" width="4.5" height="4.5" rx="0.8" />
      <rect x="9" y="2.5" width="4.5" height="4.5" rx="0.8" />
      <rect x="2.5" y="9" width="4.5" height="4.5" rx="0.8" />
      <rect x="9" y="9" width="4.5" height="4.5" rx="0.8" />
    </Svg>
  );
}

export function IconGraph({ className }: IconProps) {
  return (
    <Svg className={className}>
      <circle cx="4" cy="8" r="1.6" />
      <circle cx="12" cy="4" r="1.6" />
      <circle cx="12" cy="12" r="1.6" />
      <path d="M5.5 7.2 10.4 4.8M5.5 8.8 10.4 11.2" />
    </Svg>
  );
}

export function IconPrs({ className }: IconProps) {
  return (
    <Svg className={className}>
      <circle cx="4.5" cy="4" r="1.4" />
      <circle cx="4.5" cy="12" r="1.4" />
      <circle cx="11.5" cy="12" r="1.4" />
      <path d="M4.5 5.5v5M4.5 8h4.2a3 3 0 0 1 3 3" />
    </Svg>
  );
}

export function IconSettings({ className }: IconProps) {
  return (
    <Svg className={className}>
      <circle cx="8" cy="8" r="2.1" />
      <path d="M8 2.5v1.6M8 11.9v1.6M2.5 8h1.6M11.9 8h1.6M4.1 4.1l1.1 1.1M10.8 10.8l1.1 1.1M11.9 4.1l-1.1 1.1M5.2 10.8l-1.1 1.1" />
    </Svg>
  );
}
