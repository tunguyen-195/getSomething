import React from 'react';
import IconButton from '@mui/material/IconButton';
import Tooltip from '@mui/material/Tooltip';
import Brightness4Icon from '@mui/icons-material/Brightness4';
import Brightness7Icon from '@mui/icons-material/Brightness7';

interface DarkModeToggleProps {
  mode: 'light' | 'dark';
  toggleMode: () => void;
}

const DarkModeToggle: React.FC<DarkModeToggleProps> = ({ mode, toggleMode }) => (
  <Tooltip title={mode === 'dark' ? 'Chuyển sang chế độ sáng' : 'Chuyển sang chế độ tối'}>
    <IconButton color="inherit" onClick={toggleMode} size="large">
      {mode === 'dark' ? <Brightness7Icon /> : <Brightness4Icon />}
    </IconButton>
  </Tooltip>
);

export default DarkModeToggle; 