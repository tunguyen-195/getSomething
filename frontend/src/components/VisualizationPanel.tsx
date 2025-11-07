import React from 'react';
import { Box, Typography, Paper } from '@mui/material';
import { Timeline } from '@mui/icons-material';

interface VisualizationPanelProps {
  data: any;
  type?: string;
}

const VisualizationPanel: React.FC<VisualizationPanelProps> = ({ data, type = 'all' }) => {
  return (
    <Paper sx={{ p: 3, borderRadius: '16px', border: '2px solid #9c27b0' }}>
      <Box display="flex" alignItems="center" gap={1} mb={2}>
        <Timeline sx={{ color: '#9c27b0' }} />
        <Typography variant="h6" fontWeight={700}>VISUALIZATION</Typography>
      </Box>
      <Typography variant="body2" color="text.secondary">
        Visualization feature coming soon. Will display timeline, entity graph, and relationship map.
      </Typography>
      {data && (
        <Box mt={2}>
          <Typography variant="caption">Data loaded: {JSON.stringify(data).substring(0, 100)}...</Typography>
        </Box>
      )}
    </Paper>
  );
};

export default VisualizationPanel;