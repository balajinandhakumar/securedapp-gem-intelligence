import React from 'react';

interface IconProps {
  size?: number;
  className?: string;
}

function svgProps(size: number) {
  return {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 2,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true,
  };
}

export const IconDashboard: React.FC<IconProps> = ({ size = 18 }) => (
  <svg {...svgProps(size)}>
    <rect x="3" y="3" width="7" height="9" rx="1" />
    <rect x="14" y="3" width="7" height="5" rx="1" />
    <rect x="14" y="12" width="7" height="9" rx="1" />
    <rect x="3" y="16" width="7" height="5" rx="1" />
  </svg>
);

export const IconListSearch: React.FC<IconProps> = ({ size = 18 }) => (
  <svg {...svgProps(size)}>
    <circle cx="15" cy="9" r="3" />
    <line x1="18.5" y1="11.5" x2="21" y2="14" />
    <line x1="3" y1="6" x2="10" y2="6" />
    <line x1="3" y1="12" x2="9" y2="12" />
    <line x1="3" y1="18" x2="8" y2="18" />
  </svg>
);

export const IconClockAlert: React.FC<IconProps> = ({ size = 18 }) => (
  <svg {...svgProps(size)}>
    <circle cx="11" cy="12" r="9" />
    <polyline points="11 7 11 12 14.5 14" />
    <line x1="20" y1="6" x2="20" y2="10" />
    <line x1="20" y1="14" x2="20.01" y2="14" />
  </svg>
);

export const IconHistory: React.FC<IconProps> = ({ size = 18 }) => (
  <svg {...svgProps(size)}>
    <path d="M3 12a9 9 0 1 0 2.6-6.4L3 8" />
    <path d="M3 3v5h5" />
    <path d="M12 7.5V12l3 2" />
  </svg>
);

export const IconBox: React.FC<IconProps> = ({ size = 18 }) => (
  <svg {...svgProps(size)}>
    <path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z" />
    <path d="m3.3 7 8.7 5 8.7-5" />
    <path d="M12 22V12" />
  </svg>
);

export const IconDatabase: React.FC<IconProps> = ({ size = 18 }) => (
  <svg {...svgProps(size)}>
    <ellipse cx="12" cy="5" rx="8" ry="3" />
    <path d="M4 5v14c0 1.66 3.58 3 8 3s8-1.34 8-3V5" />
    <path d="M4 12c0 1.66 3.58 3 8 3s8-1.34 8-3" />
  </svg>
);

export const IconBell: React.FC<IconProps> = ({ size = 18 }) => (
  <svg {...svgProps(size)}>
    <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
    <path d="M13.73 21a2 2 0 0 1-3.46 0" />
  </svg>
);

export const IconSearch: React.FC<IconProps> = ({ size = 15 }) => (
  <svg {...svgProps(size)}>
    <circle cx="11" cy="11" r="8" />
    <line x1="21" y1="21" x2="16.65" y2="16.65" />
  </svg>
);

export const IconShieldCheck: React.FC<IconProps> = ({ size = 18 }) => (
  <svg {...svgProps(size)}>
    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    <path d="m9 12 2 2 4-4" />
  </svg>
);

export const IconSunMoon: React.FC<IconProps> = ({ size = 16 }) => (
  <svg {...svgProps(size)}>
    <circle cx="12" cy="12" r="4" />
    <line x1="12" y1="2" x2="12" y2="4" />
    <line x1="12" y1="20" x2="12" y2="22" />
    <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
    <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
    <line x1="2" y1="12" x2="4" y2="12" />
    <line x1="20" y1="12" x2="22" y2="12" />
    <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
    <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
  </svg>
);

export const IconTarget: React.FC<IconProps> = ({ size = 15 }) => (
  <svg {...svgProps(size)}>
    <circle cx="12" cy="12" r="9" />
    <circle cx="12" cy="12" r="5" />
    <circle cx="12" cy="12" r="1.4" />
  </svg>
);

export const IconEyeSearch: React.FC<IconProps> = ({ size = 15 }) => (
  <svg {...svgProps(size)}>
    <path d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12z" />
    <circle cx="12" cy="12" r="2.6" />
  </svg>
);

export const IconFiles: React.FC<IconProps> = ({ size = 15 }) => (
  <svg {...svgProps(size)}>
    <path d="M15 2H9a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2V7z" />
    <path d="M15 2v5h5" />
    <path d="M5 7v13a2 2 0 0 0 2 2h9" />
  </svg>
);

export const IconClock: React.FC<IconProps> = ({ size = 13 }) => (
  <svg {...svgProps(size)}>
    <circle cx="12" cy="12" r="9" />
    <polyline points="12 7 12 12 15.5 14" />
  </svg>
);

export const IconArrowRight: React.FC<IconProps> = ({ size = 13 }) => (
  <svg {...svgProps(size)}>
    <line x1="4" y1="12" x2="19" y2="12" />
    <polyline points="13 6 19 12 13 18" />
  </svg>
);

export const IconCheck: React.FC<IconProps> = ({ size = 12 }) => (
  <svg {...svgProps(size)}>
    <polyline points="20 6 9 17 4 12" />
  </svg>
);
