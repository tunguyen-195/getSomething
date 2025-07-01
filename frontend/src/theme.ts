import { createTheme } from '@mui/material/styles';

const commonTheme = {
  typography: {
    fontFamily: 'Poppins, Inter, Roboto, Helvetica, Arial, sans-serif',
    h1: { fontWeight: 900, fontSize: 40, color: '#1565c0', letterSpacing: 1.2 },
    h2: { fontWeight: 800, fontSize: 32, color: '#1976d2', letterSpacing: 1.1 },
    h3: { fontWeight: 700, fontSize: 26, color: '#d32f2f', letterSpacing: 1 },
    h4: { fontWeight: 700, fontSize: 22, color: '#1976d2', letterSpacing: 0.8 },
    h5: { fontWeight: 700, fontSize: 18, color: '#ffd600', letterSpacing: 0.5 },
    h6: { fontWeight: 700, fontSize: 16, color: '#23272f', letterSpacing: 0.2 },
    subtitle1: { fontWeight: 600, fontSize: 16, color: '#1976d2' },
    subtitle2: { fontWeight: 600, fontSize: 15, color: '#d32f2f' },
    body1: { fontWeight: 500, fontSize: 16, color: '#23272f' },
    body2: { fontWeight: 400, fontSize: 15, color: '#374151' },
    caption: { fontWeight: 400, fontSize: 13, color: '#1976d2' },
    button: { fontWeight: 700, fontSize: 16, color: '#fff', letterSpacing: 1 },
    overline: { fontWeight: 600, fontSize: 12, color: '#ffd600', letterSpacing: 2 },
  },
  shape: {
    borderRadius: 16,
  },
  components: {
    MuiCard: {
      styleOverrides: {
        root: {
          boxShadow: '0 4px 24px rgba(25, 118, 210, 0.08)',
          borderRadius: 16,
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          borderRadius: 16,
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: {
          borderRadius: 8,
          textTransform: 'none' as const,
          fontWeight: 600,
        },
      },
    },
  },
};

export const lightTheme = createTheme({
  ...commonTheme,
  palette: {
    mode: 'light',
    primary: { main: '#43a047', light: '#66bb6a', dark: '#2e7d32', contrastText: '#fff' },
    secondary: { main: '#d32f2f', light: '#ffb6c1', dark: '#b71c1c', contrastText: '#fff' },
    accent: { main: '#ffd600', light: '#fffde7', dark: '#c7b800', contrastText: '#23272f' },
    info: { main: '#1976d2', light: '#e3f2fd', dark: '#1565c0', contrastText: '#fff' },
    background: { default: '#fff', paper: '#f8fafc' },
    divider: 'rgba(67,160,71,0.12)',
    text: { primary: '#23272f', secondary: '#43a047', disabled: '#bdbdbd' },
  },
});

export const darkTheme = createTheme({
  ...commonTheme,
  palette: {
    mode: 'dark',
    primary: { main: '#43a047', light: '#66bb6a', dark: '#2e7d32', contrastText: '#fff' },
    secondary: { main: '#d32f2f', light: '#ffb6c1', dark: '#b71c1c', contrastText: '#fff' },
    accent: { main: '#ffd600', light: '#fffde7', dark: '#c7b800', contrastText: '#23272f' },
    info: { main: '#1976d2', light: '#90caf9', dark: '#1565c0', contrastText: '#fff' },
    background: { default: '#23272f', paper: '#1a237e' },
    divider: 'rgba(67,160,71,0.12)',
    text: { primary: '#fff', secondary: '#66bb6a', disabled: '#bdbdbd' },
  },
}); 