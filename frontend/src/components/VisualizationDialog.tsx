import React, { useEffect, useState } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  CircularProgress,
  Box,
  Typography,
  Alert,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import InsightsIcon from '@mui/icons-material/Insights';
import InvestigationSummaryCard from './InvestigationSummaryCard';
import { apiFetch } from '../api/client';

interface VisualizationDialogProps {
  open: boolean;
  onClose: () => void;
  taskId: string | null;
}

// Helper lấy API base URL
const API_BASE_URL = typeof window !== 'undefined' && (window as any).API_BASE_URL ? (window as any).API_BASE_URL : '';

const VisualizationDialog: React.FC<VisualizationDialogProps> = ({ open, onClose, taskId }) => {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open && taskId) {
      setLoading(true);
      setError(null);
      setData(null);

      apiFetch(`${API_BASE_URL}/api/v1/audio/tasks/${taskId}`)
        .then(res => {
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          return res.json();
        })
        .then(taskData => {
          setData(taskData);
          setLoading(false);
        })
        .catch(err => {
          console.error('Failed to load visualization data:', err);
          setError('Failed to load visualization data');
          setLoading(false);
        });
    }
  }, [open, taskId]);

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="md"
      fullWidth
      PaperProps={{
        sx: {
          borderRadius: '16px',
          border: '2px solid #9c27b0',
          boxShadow: '0 8px 32px rgba(156, 39, 176, 0.2)',
        },
      }}
    >
      <DialogTitle
        sx={{
          bgcolor: '#9c27b0',
          color: '#fff',
          fontWeight: 800,
          display: 'flex',
          alignItems: 'center',
          gap: 1,
        }}
      >
        <InsightsIcon />
        📊 DATA VISUALIZATION
      </DialogTitle>

      <DialogContent sx={{ mt: 2 }}>
        {loading ? (
          <Box
            display="flex"
            flexDirection="column"
            alignItems="center"
            justifyContent="center"
            minHeight={200}
            gap={2}
          >
            <CircularProgress size={48} sx={{ color: '#9c27b0' }} />
            <Typography variant="body1" color="text.secondary">
              Loading visualization data...
            </Typography>
          </Box>
        ) : error ? (
          <Alert severity="error">{error}</Alert>
        ) : data ? (
          data.result?.summary || data.result?.visualization_data || data.result?.context_analysis ? (
            <InvestigationSummaryCard
              summary={data.result.summary}
              contextAnalysis={data.result.visualization_data || data.result.context_analysis}
              taskId={taskId || data.id}
            />
          ) : (
            <Box minHeight={200} display="flex" alignItems="center" justifyContent="center">
              <Typography color="text.secondary">
                No visualization data available for this file.
              </Typography>
            </Box>
          )
        ) : null}
      </DialogContent>

      <DialogActions sx={{ p: 2 }}>
        <Button
          onClick={onClose}
          variant="contained"
          startIcon={<CloseIcon />}
          sx={{
            bgcolor: '#9c27b0',
            textTransform: 'none',
            fontWeight: 700,
            '&:hover': { bgcolor: '#7b1fa2' },
          }}
        >
          Close
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export default VisualizationDialog;
