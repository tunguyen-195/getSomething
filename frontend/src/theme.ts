import { createTheme } from '@mui/material/styles';

/**
 * Cherry2 UI Theme - Refined Cherry Rose
 *
 * Design System:
 * - Warm rose/coral accent (evokes cherry)
 * - Slate neutral base
 * - Bundled Roboto font family
 * - Minimal, professional styling
 */

declare module '@mui/material/styles' {
  interface Palette {
    accent: Palette['primary'];
  }
  interface PaletteOptions {
    accent?: PaletteOptions['primary'];
  }
}

// Design tokens - Cherry Rose Theme
const tokens = {
  colors: {
    // Backgrounds - Slate base
    bgPrimary: '#0f172a',
    bgSecondary: '#1e293b',
    bgTertiary: '#334155',

    // Text
    textPrimary: '#f8fafc',
    textSecondary: '#94a3b8',
    textTertiary: '#64748b',

    // Cherry Rose Accent - Warm, pleasant
    cherryPrimary: '#e11d48',    // Rose-600 - main cherry
    cherryLight: '#fb7185',      // Rose-400 - hover
    cherryDark: '#be123c',       // Rose-700 - pressed
    cherryMuted: 'rgba(225, 29, 72, 0.12)', // Subtle backgrounds

    // Warm coral for secondary actions
    coral: '#f97316',
    coralMuted: 'rgba(249, 115, 22, 0.12)',

    // Semantic
    success: '#22c55e',
    successMuted: 'rgba(34, 197, 94, 0.12)',
    warning: '#eab308',
    warningMuted: 'rgba(234, 179, 8, 0.12)',
    error: '#ef4444',
    errorMuted: 'rgba(239, 68, 68, 0.12)',
    info: '#0ea5e9',
    infoMuted: 'rgba(14, 165, 233, 0.12)',

    // Borders
    border: 'rgba(255, 255, 255, 0.08)',
    borderHover: 'rgba(225, 29, 72, 0.4)',
  },

  borderRadius: {
    sm: 6,
    md: 8,
    lg: 12,
    xl: 16,
  },
};

const typography = {
  fontFamily: "'Roboto', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
  h1: { fontWeight: 700, fontSize: '2rem', letterSpacing: '-0.02em' },
  h2: { fontWeight: 700, fontSize: '1.5rem', letterSpacing: '-0.01em' },
  h3: { fontWeight: 600, fontSize: '1.25rem', letterSpacing: '-0.01em' },
  h4: { fontWeight: 600, fontSize: '1.125rem' },
  h5: { fontWeight: 600, fontSize: '1rem' },
  h6: { fontWeight: 600, fontSize: '0.875rem' },
  subtitle1: { fontWeight: 500, fontSize: '1rem' },
  subtitle2: { fontWeight: 500, fontSize: '0.875rem' },
  body1: { fontWeight: 400, fontSize: '0.9375rem', lineHeight: 1.6 },
  body2: { fontWeight: 400, fontSize: '0.875rem', lineHeight: 1.5 },
  caption: { fontWeight: 400, fontSize: '0.75rem' },
  button: { fontWeight: 500, fontSize: '0.875rem', textTransform: 'none' as const },
  overline: { fontWeight: 500, fontSize: '0.75rem', letterSpacing: '0.05em' },
};

const components = {
  MuiCssBaseline: {
    styleOverrides: {
      body: {
        scrollbarWidth: 'thin',
        scrollbarColor: `${tokens.colors.bgTertiary} ${tokens.colors.bgPrimary}`,
        '&::-webkit-scrollbar': { width: 8 },
        '&::-webkit-scrollbar-track': { background: tokens.colors.bgPrimary },
        '&::-webkit-scrollbar-thumb': {
          background: tokens.colors.bgTertiary,
          borderRadius: 4,
        },
      },
    },
  },
  MuiButton: {
    styleOverrides: {
      root: {
        borderRadius: tokens.borderRadius.md,
        textTransform: 'none' as const,
        fontWeight: 500,
        padding: '8px 16px',
        boxShadow: 'none',
        '&:hover': { boxShadow: 'none' },
      },
      containedPrimary: {
        background: tokens.colors.cherryPrimary,
        '&:hover': { background: tokens.colors.cherryLight },
      },
    },
  },
  MuiPaper: {
    styleOverrides: {
      root: {
        borderRadius: tokens.borderRadius.lg,
        backgroundImage: 'none',
        border: `1px solid ${tokens.colors.border}`,
      },
    },
  },
  MuiCard: {
    styleOverrides: {
      root: {
        borderRadius: tokens.borderRadius.lg,
        boxShadow: 'none',
        border: `1px solid ${tokens.colors.border}`,
      },
    },
  },
  MuiTab: {
    styleOverrides: {
      root: {
        textTransform: 'none' as const,
        fontWeight: 500,
        fontSize: '0.875rem',
        minHeight: 44,
        padding: '8px 16px',
      },
    },
  },
  MuiTabs: {
    styleOverrides: {
      indicator: {
        height: 2,
        borderRadius: 1,
        backgroundColor: tokens.colors.cherryPrimary,
      },
    },
  },
  MuiChip: {
    styleOverrides: {
      root: {
        borderRadius: tokens.borderRadius.sm,
        fontWeight: 500,
        fontSize: '0.75rem',
      },
    },
  },
  MuiDialog: {
    styleOverrides: {
      paper: {
        borderRadius: tokens.borderRadius.xl,
        border: `1px solid ${tokens.colors.border}`,
      },
    },
  },
  MuiTextField: {
    styleOverrides: {
      root: {
        '& .MuiOutlinedInput-root': {
          borderRadius: tokens.borderRadius.md,
        },
      },
    },
  },
  MuiDrawer: {
    styleOverrides: {
      paper: { border: 'none' },
    },
  },
  MuiListItem: {
    styleOverrides: {
      root: { borderRadius: tokens.borderRadius.md },
    },
  },
};

// Dark theme (primary)
export const darkTheme = createTheme({
  palette: {
    mode: 'dark',
    primary: {
      main: tokens.colors.cherryPrimary,
      light: tokens.colors.cherryLight,
      dark: tokens.colors.cherryDark,
      contrastText: '#fff',
    },
    secondary: {
      main: tokens.colors.coral,
      light: '#fdba74',
      dark: '#ea580c',
    },
    accent: {
      main: tokens.colors.cherryPrimary,
      light: tokens.colors.cherryLight,
      dark: tokens.colors.cherryDark,
      contrastText: '#fff',
    },
    success: { main: tokens.colors.success },
    warning: { main: tokens.colors.warning },
    error: { main: tokens.colors.error },
    info: { main: tokens.colors.info },
    background: {
      default: tokens.colors.bgPrimary,
      paper: tokens.colors.bgSecondary,
    },
    divider: tokens.colors.border,
    text: {
      primary: tokens.colors.textPrimary,
      secondary: tokens.colors.textSecondary,
      disabled: tokens.colors.textTertiary,
    },
  },
  typography,
  shape: { borderRadius: tokens.borderRadius.md },
  components,
});

// Light theme
export const lightTheme = createTheme({
  palette: {
    mode: 'light',
    primary: {
      main: tokens.colors.cherryPrimary,
      light: tokens.colors.cherryLight,
      dark: tokens.colors.cherryDark,
      contrastText: '#fff',
    },
    secondary: {
      main: tokens.colors.coral,
      light: '#fdba74',
      dark: '#ea580c',
    },
    accent: {
      main: tokens.colors.cherryPrimary,
      light: tokens.colors.cherryLight,
      dark: tokens.colors.cherryDark,
      contrastText: '#fff',
    },
    success: { main: tokens.colors.success },
    warning: { main: tokens.colors.warning },
    error: { main: tokens.colors.error },
    info: { main: tokens.colors.info },
    background: {
      default: '#f8fafc',
      paper: '#ffffff',
    },
    divider: 'rgba(0, 0, 0, 0.08)',
    text: {
      primary: '#0f172a',
      secondary: '#64748b',
      disabled: '#94a3b8',
    },
  },
  typography,
  shape: { borderRadius: tokens.borderRadius.md },
  components: {
    ...components,
    MuiPaper: {
      styleOverrides: {
        root: {
          borderRadius: tokens.borderRadius.lg,
          backgroundImage: 'none',
          border: '1px solid rgba(0, 0, 0, 0.08)',
        },
      },
    },
  },
});

export { tokens };
