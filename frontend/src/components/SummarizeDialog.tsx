import React, { useState } from 'react';
import { Dialog, DialogTitle, DialogContent, DialogActions, Button, Select, MenuItem, Typography, Box, FormControl, FormControlLabel, Checkbox } from '@mui/material';
import { Description, Close } from '@mui/icons-material';

interface SummarizeDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: (options: { model_name: string; summary_type: string; include_context_analysis: boolean }) => void;
  transcriptLength?: number;
}

const SummarizeDialog: React.FC<SummarizeDialogProps> = ({ open, onClose, onConfirm, transcriptLength }) => {
  const [modelName, setModelName] = useState('configured_api');
  const [summaryType, setSummaryType] = useState('investigation');
  const [includeContext, setIncludeContext] = useState(true);

  const handleConfirm = () => {
    onConfirm({ model_name: modelName, summary_type: summaryType, include_context_analysis: includeContext });
    onClose();
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth PaperProps={{ sx: { borderRadius: '16px', border: '2px solid #ffd600' } }}>
      <DialogTitle sx={{ bgcolor: '#ff9800', color: '#fff', fontWeight: 800, display: 'flex', alignItems: 'center', gap: 1 }}>
        <Description /> SUMMARIZE TRANSCRIPT
      </DialogTitle>
      <DialogContent sx={{ mt: 3 }}>
        <Typography variant="body2" color="text.secondary" mb={2}>Transcript: {transcriptLength || 0} words</Typography>

        <Typography variant="subtitle2" fontWeight={700} mb={1}>AI MODEL</Typography>
        <FormControl fullWidth sx={{ mb: 2 }}>
          <Select value={modelName} onChange={(e) => setModelName(e.target.value)} size="small">
            <MenuItem value="configured_api">GPT OSS 120</MenuItem>
          </Select>
        </FormControl>

        <Typography variant="subtitle2" fontWeight={700} mb={1}>SUMMARY TYPE</Typography>
        <FormControl fullWidth sx={{ mb: 2 }}>
          <Select value={summaryType} onChange={(e) => setSummaryType(e.target.value)} size="small">
            <MenuItem value="brief">Brief (Key points only)</MenuItem>
            <MenuItem value="detailed">Detailed (Full analysis)</MenuItem>
            <MenuItem value="investigation">Investigation (For police work)</MenuItem>
          </Select>
        </FormControl>

        <FormControlLabel
          control={<Checkbox checked={includeContext} onChange={(e) => setIncludeContext(e.target.checked)} sx={{ color: '#ff9800' }} />}
          label="Include AI analysis (entities, actions, risk signals)"
        />
      </DialogContent>
      <DialogActions sx={{ p: 3, gap: 2 }}>
        <Button onClick={onClose} variant="outlined" startIcon={<Close />} sx={{ textTransform: 'none' }}>Cancel</Button>
        <Button onClick={handleConfirm} variant="contained" startIcon={<Description />} sx={{ bgcolor: '#ff9800', textTransform: 'none', fontWeight: 700 }}>
          Start Summary
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export default SummarizeDialog;
