import React from 'react';
import { Chip } from '@mui/material';

interface StatusBadgeProps {
  status: 'uploaded' | 'transcribing' | 'transcribed' | 'summarizing' | 'summarized' | 'failed';
}

const StatusBadge: React.FC<StatusBadgeProps> = ({ status }) => {
  const colors: Record<string, string> = {
    uploaded: '#1976d2',
    transcribing: '#ffd600',
    transcribed: '#43a047',
    summarizing: '#ff9800',
    summarized: '#9c27b0',
    failed: '#d32f2f',
  };

  const labels: Record<string, string> = {
    uploaded: 'Uploaded',
    transcribing: 'Transcribing...',
    transcribed: 'Transcribed',
    summarizing: 'Summarizing...',
    summarized: 'Summarized',
    failed: 'Failed',
  };

  return (
    <Chip
      label={labels[status] || status}
      sx={{
        bgcolor: colors[status] || '#757575',
        color: '#fff',
        fontWeight: 700,
        boxShadow: `0 2px 8px ${colors[status]}40`,
      }}
    />
  );
};

export default StatusBadge;