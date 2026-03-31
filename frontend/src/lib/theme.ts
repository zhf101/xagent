export type ThemeMode = 'dark' | 'light' | 'system';

export interface ThemeColors {
  background: string;
  foreground: string;
  card: string;
  cardForeground: string;
  popover: string;
  popoverForeground: string;
  primary: string;
  primaryForeground: string;
  secondary: string;
  secondaryForeground: string;
  muted: string;
  mutedForeground: string;
  accent: string;
  accentForeground: string;
  destructive: string;
  destructiveForeground: string;
  border: string;
  input: string;
  ring: string;
  // Extended colors
  cardHover?: string;
  borderHighlight?: string;
  accentBg?: string;
  accentBorder?: string;
  shadowColor?: string;
  // Gradient text colors
  gradientFrom?: string;
  gradientTo?: string;
  // Sidebar active state colors
  sidebarActiveBgFrom?: string;
  sidebarActiveBgTo?: string;
  sidebarActiveText?: string;
  sidebarActiveBorder?: string;
}

export interface Theme {
  name: string;
  mode: ThemeMode;
  colors: ThemeColors;
}

/* 
 * XAgent 主题系统 - 基于 http2mcp 配色方案
 * 所有主题主色统一为红色 #d33b32 (HSL: 3 70% 52%)
 */
export const themes: Record<string, Theme> = {
  dark: {
    name: 'Dark',
    mode: 'dark',
    colors: {
      background: '220 15% 10%',
      foreground: '210 40% 98%',
      card: '220 15% 14%',
      cardForeground: '210 40% 98%',
      popover: '220 15% 14%',
      popoverForeground: '210 40% 98%',
      primary: '3 70% 52%', // #d33b32 - http2mcp 红色
      primaryForeground: '0 0% 100%',
      secondary: '220 15% 20%',
      secondaryForeground: '210 40% 98%',
      muted: '220 15% 18%',
      mutedForeground: '220 12% 65%',
      accent: '220 15% 18%',
      accentForeground: '210 40% 98%',
      destructive: '0 84.2% 60.2%',
      destructiveForeground: '210 40% 98%',
      border: '220 15% 20%',
      input: '220 15% 20%',
      ring: '3 70% 52%',
      // Extended colors
      gradientFrom: '3 70% 52%', // 主色红
      gradientTo: '3 75% 61%', // 悬停红
      sidebarActiveBgFrom: '3 70% 52% / 0.15',
      sidebarActiveBgTo: '3 70% 52% / 0',
      sidebarActiveText: '3 70% 52%',
      sidebarActiveBorder: '3 70% 52%',
    },
  },
  light: {
    name: 'Light',
    mode: 'light',
    colors: {
      background: '0 33.3% 98.8%',        // #fdfbfb 暖白
      foreground: '0 2.0% 19.6%',         // #333131 主文字
      card: '0 9.1% 95.7%',               // #f5f3f3 浅灰卡片
      cardForeground: '0 2.0% 19.6%',
      popover: '0 33.3% 98.8%',
      popoverForeground: '0 2.0% 19.6%',
      primary: '3.4 64.7% 51.2%',         // #d33b32 深红
      primaryForeground: '0 0% 100%',
      secondary: '0 9.1% 95.7%',          // #f5f3f3
      secondaryForeground: '0 1.4% 59.4%',// #999696 中灰
      muted: '0 9.1% 95.7%',              // #f5f3f3
      mutedForeground: '0 1.4% 59.4%',    // #999696 中灰
      accent: '0 9.1% 95.7%',
      accentForeground: '0 2.0% 19.6%',
      destructive: '6 81.3% 58%',         // #eb4e3d 警示红
      destructiveForeground: '0 0% 100%',
      border: '0 4.3% 91%',               // #e9e7e7 浅灰分割线
      input: '0 4.3% 91%',
      ring: '206 17% 57%',                // #8294a2 冷灰蓝
      // Extended colors
      gradientFrom: '3.4 64.7% 51.2%',
      gradientTo: '3.8 76% 59.2%',        // Hover红
      sidebarActiveBgFrom: '3.4 64.7% 51.2% / 0.1',
      sidebarActiveBgTo: '3.4 64.7% 51.2% / 0',
      sidebarActiveText: '3.4 64.7% 51.2%',
      sidebarActiveBorder: '3.4 64.7% 51.2%',
    },
  },
  blue: {
    name: 'Dark Blue',
    mode: 'dark',
    colors: {
      background: '220 25% 12%',
      foreground: '210 40% 98%',
      card: '220 25% 16%',
      cardForeground: '210 40% 98%',
      popover: '220 25% 16%',
      popoverForeground: '210 40% 98%',
      primary: '3 70% 52%', // 统一红色主色
      primaryForeground: '0 0% 100%',
      secondary: '220 25% 22%',
      secondaryForeground: '210 40% 98%',
      muted: '220 20% 20%',
      mutedForeground: '220 15% 65%',
      accent: '220 25% 22%',
      accentForeground: '210 40% 98%',
      destructive: '0 84.2% 60.2%',
      destructiveForeground: '210 40% 98%',
      border: '220 25% 22%',
      input: '220 25% 22%',
      ring: '3 70% 52%',
      gradientFrom: '3 70% 52%',
      gradientTo: '3 75% 61%',
      sidebarActiveBgFrom: '3 70% 52% / 0.15',
      sidebarActiveBgTo: '3 70% 52% / 0',
      sidebarActiveText: '3 70% 52%',
      sidebarActiveBorder: '3 70% 52%',
    },
  },
  green: {
    name: 'Dark Green',
    mode: 'dark',
    colors: {
      background: '142 28% 12%',
      foreground: '210 40% 98%',
      card: '142 28% 16%',
      cardForeground: '210 40% 98%',
      popover: '142 28% 16%',
      popoverForeground: '210 40% 98%',
      primary: '3 70% 52%', // 统一红色主色
      primaryForeground: '0 0% 100%',
      secondary: '142 25% 20%',
      secondaryForeground: '210 40% 98%',
      muted: '142 20% 18%',
      mutedForeground: '142 15% 65%',
      accent: '142 25% 20%',
      accentForeground: '210 40% 98%',
      destructive: '0 84.2% 60.2%',
      destructiveForeground: '210 40% 98%',
      border: '142 25% 22%',
      input: '142 25% 22%',
      ring: '3 70% 52%',
      gradientFrom: '3 70% 52%',
      gradientTo: '3 75% 61%',
      sidebarActiveBgFrom: '3 70% 52% / 0.15',
      sidebarActiveBgTo: '3 70% 52% / 0',
      sidebarActiveText: '3 70% 52%',
      sidebarActiveBorder: '3 70% 52%',
    },
  },
  purple: {
    name: 'Dark Purple',
    mode: 'dark',
    colors: {
      background: '262 28% 12%',
      foreground: '210 40% 98%',
      card: '262 28% 16%',
      cardForeground: '210 40% 98%',
      popover: '262 28% 16%',
      popoverForeground: '210 40% 98%',
      primary: '3 70% 52%', // 统一红色主色
      primaryForeground: '0 0% 100%',
      secondary: '262 25% 20%',
      secondaryForeground: '210 40% 98%',
      muted: '262 20% 18%',
      mutedForeground: '262 15% 65%',
      accent: '262 25% 20%',
      accentForeground: '210 40% 98%',
      destructive: '0 84.2% 60.2%',
      destructiveForeground: '210 40% 98%',
      border: '262 25% 22%',
      input: '262 25% 22%',
      ring: '3 70% 52%',
      gradientFrom: '3 70% 52%',
      gradientTo: '3 75% 61%',
      sidebarActiveBgFrom: '3 70% 52% / 0.15',
      sidebarActiveBgTo: '3 70% 52% / 0',
      sidebarActiveText: '3 70% 52%',
      sidebarActiveBorder: '3 70% 52%',
    },
  },
  cyber: {
    name: 'Cyber',
    mode: 'dark',
    colors: {
      background: '222 47% 8%',
      foreground: '0 0% 100%',
      card: '222 47% 12%',
      cardForeground: '0 0% 100%',
      popover: '222 47% 12%',
      popoverForeground: '0 0% 100%',
      primary: '3 70% 52%', // 统一红色主色
      primaryForeground: '0 0% 100%',
      secondary: '217 33% 17%',
      secondaryForeground: '210 40% 98%',
      muted: '215 25% 20%',
      mutedForeground: '215 16% 55%',
      accent: '215 25% 20%',
      accentForeground: '210 40% 98%',
      destructive: '0 84% 60%',
      destructiveForeground: '0 0% 100%',
      border: '217 33% 20%',
      input: '222 47% 10%',
      ring: '3 70% 52%',
      cardHover: '215 25% 20%',
      borderHighlight: '215 25% 35%',
      accentBg: '3 70% 52% / 0.1',
      accentBorder: '3 70% 52% / 0.2',
      shadowColor: '0 0% 0% / 0.5',
      gradientFrom: '3 70% 52%',
      gradientTo: '3 75% 61%',
      sidebarActiveBgFrom: '3 70% 52% / 0.15',
      sidebarActiveBgTo: '3 70% 52% / 0',
      sidebarActiveText: '3 70% 52%',
      sidebarActiveBorder: '3 70% 52%',
    },
  },
  cyberLight: {
    name: 'Cyber Light',
    mode: 'light',
    colors: {
      background: '210 40% 98%',
      foreground: '220 19% 14%',
      card: '0 0% 100%',
      cardForeground: '220 19% 14%',
      popover: '0 0% 100%',
      popoverForeground: '220 19% 14%',
      primary: '3 70% 52%', // 统一红色主色
      primaryForeground: '0 0% 100%',
      secondary: '210 40% 96%',
      secondaryForeground: '220 19% 14%',
      muted: '210 30% 95%',
      mutedForeground: '220 12% 50%',
      accent: '210 40% 96%',
      accentForeground: '220 19% 14%',
      destructive: '0 84% 60%',
      destructiveForeground: '210 40% 98%',
      border: '214 31% 91%',
      input: '210 40% 96%',
      ring: '3 70% 52%',
      cardHover: '210 40% 96%',
      borderHighlight: '213 27% 84%',
      accentBg: '3 70% 52% / 0.1',
      accentBorder: '3 70% 52% / 0.2',
      shadowColor: '0 0% 0% / 0.05',
      gradientFrom: '3 70% 52%',
      gradientTo: '3 75% 61%',
      sidebarActiveBgFrom: '3 70% 52% / 0.1',
      sidebarActiveBgTo: '3 70% 52% / 0',
      sidebarActiveText: '3 70% 52%',
      sidebarActiveBorder: '3 70% 52%',
    },
  },
};

export function getThemeFromEnv(): string {
  return process.env.NEXT_PUBLIC_THEME || 'light';
}

export function applyTheme(themeName: string): void {
  const theme = themes[themeName] || themes.light;
  const root = document.documentElement;

  // Apply CSS custom properties
  root.style.setProperty('--background', theme.colors.background);
  root.style.setProperty('--foreground', theme.colors.foreground);
  root.style.setProperty('--card', theme.colors.card);
  root.style.setProperty('--card-foreground', theme.colors.cardForeground);
  root.style.setProperty('--popover', theme.colors.popover);
  root.style.setProperty('--popover-foreground', theme.colors.popoverForeground);
  root.style.setProperty('--primary', theme.colors.primary);
  root.style.setProperty('--primary-foreground', theme.colors.primaryForeground);
  root.style.setProperty('--secondary', theme.colors.secondary);
  root.style.setProperty('--secondary-foreground', theme.colors.secondaryForeground);
  root.style.setProperty('--muted', theme.colors.muted);
  root.style.setProperty('--muted-foreground', theme.colors.mutedForeground);
  root.style.setProperty('--accent', theme.colors.accent);
  root.style.setProperty('--accent-foreground', theme.colors.accentForeground);
  root.style.setProperty('--destructive', theme.colors.destructive);
  root.style.setProperty('--destructive-foreground', theme.colors.destructiveForeground);
  root.style.setProperty('--border', theme.colors.border);
  root.style.setProperty('--input', theme.colors.input);
  root.style.setProperty('--ring', theme.colors.ring);

  // Apply extended color properties if available
  if (theme.colors.cardHover) {
    root.style.setProperty('--card-hover', theme.colors.cardHover);
  }
  if (theme.colors.borderHighlight) {
    root.style.setProperty('--border-highlight', theme.colors.borderHighlight);
  }
  if (theme.colors.accentBg) {
    root.style.setProperty('--accent-bg', theme.colors.accentBg);
  }
  if (theme.colors.accentBorder) {
    root.style.setProperty('--accent-border', theme.colors.accentBorder);
  }
  if (theme.colors.shadowColor) {
    root.style.setProperty('--shadow-color', theme.colors.shadowColor);
  }

  // Apply gradient text colors
  if (theme.colors.gradientFrom) {
    root.style.setProperty('--gradient-from', theme.colors.gradientFrom);
  }
  if (theme.colors.gradientTo) {
    root.style.setProperty('--gradient-to', theme.colors.gradientTo);
  }

  // Apply sidebar active state colors
  if (theme.colors.sidebarActiveBgFrom) {
    root.style.setProperty('--sidebar-active-bg-from', theme.colors.sidebarActiveBgFrom);
  }
  if (theme.colors.sidebarActiveBgTo) {
    root.style.setProperty('--sidebar-active-bg-to', theme.colors.sidebarActiveBgTo);
  }
  if (theme.colors.sidebarActiveText) {
    root.style.setProperty('--sidebar-active-text', theme.colors.sidebarActiveText);
  }
  if (theme.colors.sidebarActiveBorder) {
    root.style.setProperty('--sidebar-active-border', theme.colors.sidebarActiveBorder);
  }

  // Apply theme class to body
  const body = document.body;
  body.className = body.className.replace(/\b(theme-\w+)\b/g, '');
  body.classList.add(`theme-${themeName}`);

  // Apply dark/light mode
  if (theme.mode === 'dark') {
    document.documentElement.classList.add('dark');
  } else {
    document.documentElement.classList.remove('dark');
  }
}
