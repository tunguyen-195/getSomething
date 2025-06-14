import { createTheme } from '@mui/material/styles';

const commonTheme = {
  typography: {
    fontFamily: 'Roboto, Helvetica, Arial, sans-serif',
    h6: { fontWeight: 700 },
    h5: { fontWeight: 700 },
    button: { fontWeight: 600, fontSize: 16 },
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
    primary: { main: '#1976d2' },
    secondary: { main: '#dc004e' },
    background: { default: '#f5f7fa', paper: '#fff' },
    text: { primary: '#1a237e', secondary: '#5c6bc0' },
  },
});

export const darkTheme = createTheme({
  ...commonTheme,
  palette: {
    mode: 'dark',
    primary: { main: '#90caf9' },
    secondary: { main: '#f48fb1' },
    background: { default: '#121212', paper: '#23272f' },
    text: { primary: '#fff', secondary: '#b0bec5' },
  },
}); 