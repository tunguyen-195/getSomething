import React, { useState } from 'react';
import { Dialog, DialogTitle, DialogContent, DialogActions, Button, Select, MenuItem, Typography, FormControl, TextField } from '@mui/material';
import { Description, Close } from '@mui/icons-material';
import {
  DEFAULT_INTERACTIVE_SUMMARY_TYPE,
  DEFAULT_INVESTIGATION_SUMMARY_MAX_LENGTH,
  DEFAULT_INVESTIGATION_SUMMARY_MIN_LENGTH,
  DEFAULT_SUMMARY_MAX_LENGTH,
  DEFAULT_SUMMARY_MIN_LENGTH,
  normalizeSummaryUserPrompt,
  SUMMARY_USER_PROMPT_MAX_LENGTH,
} from '../api/client';
import type { SummaryDialogOptions, SummaryType } from '../api/client';

interface SummarizeDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: (options: SummaryDialogOptions) => void;
  transcriptLength?: number;
}

const SummarizeDialog: React.FC<SummarizeDialogProps> = ({ open, onClose, onConfirm, transcriptLength }) => {
  const [modelName, setModelName] = useState('auto');
  const [summaryType, setSummaryType] = useState<SummaryType>(DEFAULT_INTERACTIVE_SUMMARY_TYPE);
  const [userPrompt, setUserPrompt] = useState('');
  const userPromptLength = Array.from(userPrompt.trim()).length;
  const userPromptTooLong = userPromptLength > SUMMARY_USER_PROMPT_MAX_LENGTH;

  const handleClose = () => {
    setUserPrompt('');
    onClose();
  };

  const handleConfirm = () => {
    if (userPromptTooLong) return;
    const investigation = summaryType === 'investigation';
    onConfirm({
      model_name: modelName,
      summary_type: summaryType,
      user_prompt: normalizeSummaryUserPrompt(userPrompt),
      include_context_analysis: false,
      min_length: investigation ? DEFAULT_INVESTIGATION_SUMMARY_MIN_LENGTH : DEFAULT_SUMMARY_MIN_LENGTH,
      max_length: investigation ? DEFAULT_INVESTIGATION_SUMMARY_MAX_LENGTH : DEFAULT_SUMMARY_MAX_LENGTH,
      length_mode: 'auto',
      investigation_scenario: 'auto',
    });
    handleClose();
  };

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth PaperProps={{ sx: { borderRadius: '16px', border: '2px solid #ffd600' } }}>
      <DialogTitle sx={{ bgcolor: '#ff9800', color: '#fff', fontWeight: 800, display: 'flex', alignItems: 'center', gap: 1 }}>
        <Description /> SUMMARIZE TRANSCRIPT
      </DialogTitle>
      <DialogContent sx={{ mt: 3 }}>
        <Typography variant="body2" color="text.secondary" mb={2}>Transcript: {transcriptLength || 0} words</Typography>

        <Typography variant="subtitle2" fontWeight={700} mb={1}>AI MODEL</Typography>
        <FormControl fullWidth sx={{ mb: 2 }}>
          <Select value={modelName} onChange={(e) => setModelName(e.target.value)} size="small">
            <MenuItem value="auto">Configured offline model (recommended)</MenuItem>
            <MenuItem value="llama3.2:3b">Llama 3.2 3B (validated structured output)</MenuItem>
            <MenuItem value="gemma2:9b">Gemma 2 9B (summary only; analysis experimental)</MenuItem>
          </Select>
        </FormControl>

        <Typography variant="subtitle2" fontWeight={700} mb={1}>SUMMARY TYPE</Typography>
        <FormControl fullWidth sx={{ mb: 2 }}>
          <Select value={summaryType} onChange={(e) => setSummaryType(e.target.value as SummaryType)} size="small">
            <MenuItem value="brief">Brief (Key points only)</MenuItem>
            <MenuItem value="detailed">Detailed (More complete summary)</MenuItem>
            <MenuItem value="investigation">Investigation (For police work)</MenuItem>
          </Select>
        </FormControl>

        <Typography variant="subtitle2" fontWeight={700} mb={1}>YÊU CẦU TÓM TẮT (TÙY CHỌN)</Typography>
        <TextField
          value={userPrompt}
          onChange={(event) => setUserPrompt(event.target.value)}
          multiline
          minRows={3}
          maxRows={7}
          fullWidth
          error={userPromptTooLong}
          placeholder="Ví dụ: Tập trung vào các mốc thời gian và hành động đã thống nhất"
          helperText={userPromptTooLong
            ? `Tối đa ${SUMMARY_USER_PROMPT_MAX_LENGTH.toLocaleString('vi-VN')} ký tự`
            : `${userPromptLength.toLocaleString('vi-VN')}/${SUMMARY_USER_PROMPT_MAX_LENGTH.toLocaleString('vi-VN')}`}
          inputProps={{ 'aria-label': 'Yêu cầu tóm tắt tùy chọn' }}
          sx={{ mb: 2 }}
        />

        <Typography variant="body2" color="text.secondary">
          Độ dài được tự động ước lượng theo tỷ lệ nội dung nguồn và có thể mở rộng khi hội thoại chứa nhiều thông tin. Transcript dài sẽ được tóm tắt theo từng phần rồi tổng hợp; Analysis được chạy riêng khi bạn yêu cầu.
        </Typography>
      </DialogContent>
      <DialogActions sx={{ p: 3, gap: 2 }}>
        <Button onClick={handleClose} variant="outlined" startIcon={<Close />} sx={{ textTransform: 'none' }}>Cancel</Button>
        <Button disabled={userPromptTooLong} onClick={handleConfirm} variant="contained" startIcon={<Description />} sx={{ bgcolor: '#ff9800', textTransform: 'none', fontWeight: 700 }}>
          Start Summary
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export default SummarizeDialog;
