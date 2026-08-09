import React, { useState } from 'react';
import { Dialog, DialogTitle, DialogContent, DialogActions, Button, Select, MenuItem, Typography, Box, FormControl, FormControlLabel, Checkbox, TextField } from '@mui/material';
import { Description, Close } from '@mui/icons-material';
import {
  DEFAULT_SUMMARY_MAX_LENGTH,
  DEFAULT_SUMMARY_MIN_LENGTH,
  DEFAULT_SUMMARY_TYPE,
} from '../api/client';
import type { SummaryDialogOptions, SummaryType } from '../api/client';

interface SummarizeDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: (options: SummaryDialogOptions) => void;
  transcriptLength?: number;
}

const SummarizeDialog: React.FC<SummarizeDialogProps> = ({ open, onClose, onConfirm, transcriptLength }) => {
  const [modelName, setModelName] = useState('vistral');
  const [summaryType, setSummaryType] = useState<SummaryType>(DEFAULT_SUMMARY_TYPE);
  const [includeContext, setIncludeContext] = useState(true);
  const [minLength, setMinLength] = useState(DEFAULT_SUMMARY_MIN_LENGTH);
  const [maxLength, setMaxLength] = useState(DEFAULT_SUMMARY_MAX_LENGTH);

  const boundsValid = Number.isInteger(minLength)
    && Number.isInteger(maxLength)
    && minLength >= 0
    && maxLength >= 1
    && minLength <= maxLength;

  const handleConfirm = () => {
    if (!boundsValid) return;
    onConfirm({
      model_name: modelName,
      summary_type: summaryType,
      include_context_analysis: includeContext,
      min_length: minLength,
      max_length: maxLength,
    });
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
            <MenuItem value="vistral">🇻🇳 Vistral 7B (Vietnamese, Llama.cpp - Fast)</MenuItem>
            <MenuItem value="qwen3">🌏 Qwen3 8B (32K Context, Llama.cpp)</MenuItem>
            <MenuItem value="forensic">🔍 Forensic Analysis (Vistral + Template)</MenuItem>
            <MenuItem value="gemma2:9b">Gemma 2 9B (Ollama Fallback)</MenuItem>
          </Select>
        </FormControl>

        <Typography variant="subtitle2" fontWeight={700} mb={1}>SUMMARY TYPE</Typography>
        <FormControl fullWidth sx={{ mb: 2 }}>
          <Select value={summaryType} onChange={(e) => setSummaryType(e.target.value as SummaryType)} size="small">
            <MenuItem value="brief">Brief (Key points only)</MenuItem>
            <MenuItem value="detailed">Detailed (Full analysis)</MenuItem>
            <MenuItem value="investigation">Investigation (For police work)</MenuItem>
          </Select>
        </FormControl>

        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' }, gap: 2, mb: 1 }}>
          <TextField
            label="Target minimum (advisory)"
            type="number"
            size="small"
            value={minLength}
            inputProps={{ min: 0, step: 1 }}
            onChange={(event) => setMinLength(Number(event.target.value))}
            error={!boundsValid}
          />
          <TextField
            label="Maximum words (enforced)"
            type="number"
            size="small"
            value={maxLength}
            inputProps={{ min: 1, step: 1 }}
            onChange={(event) => setMaxLength(Number(event.target.value))}
            error={!boundsValid}
          />
        </Box>
        {!boundsValid && (
          <Typography variant="caption" color="error" display="block" mb={1}>
            Length bounds require 0 &lt;= target minimum &lt;= maximum.
          </Typography>
        )}

        <FormControlLabel
          control={<Checkbox checked={includeContext} onChange={(e) => setIncludeContext(e.target.checked)} sx={{ color: '#ff9800' }} />}
          label="Include context analysis (entities, actions, privacy)"
        />
      </DialogContent>
      <DialogActions sx={{ p: 3, gap: 2 }}>
        <Button onClick={onClose} variant="outlined" startIcon={<Close />} sx={{ textTransform: 'none' }}>Cancel</Button>
        <Button onClick={handleConfirm} disabled={!boundsValid} variant="contained" startIcon={<Description />} sx={{ bgcolor: '#ff9800', textTransform: 'none', fontWeight: 700 }}>
          Start Summary
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export default SummarizeDialog;
