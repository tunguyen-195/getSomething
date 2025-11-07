import React, { useState } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  FormControl,
  FormControlLabel,
  Checkbox,
  Select,
  MenuItem,
  Typography,
  Box,
  Paper,
  Divider,
} from '@mui/material';
import { RecordVoiceOver, Speed, Close } from '@mui/icons-material';

interface TranscribeDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: (options: {
    enable_diarization: boolean;
    diarization_method: string;
    fast_mode: boolean;
  }) => void;
  filename: string;
  duration?: number;
}

const TranscribeDialog: React.FC<TranscribeDialogProps> = ({
  open,
  onClose,
  onConfirm,
  filename,
  duration,
}) => {
  const [enableDiarization, setEnableDiarization] = useState(true);
  const [diarizationMethod, setDiarizationMethod] = useState('pyannote');
  const [fastMode, setFastMode] = useState(true);

  const handleConfirm = () => {
    onConfirm({
      enable_diarization: enableDiarization,
      diarization_method: diarizationMethod,
      fast_mode: fastMode,
    });
    onClose();
  };

  const estimateTime = () => {
    if (!duration) return 'N/A';
    const factor = fastMode ? 0.1 : 0.3; // Fast mode ~10x, normal ~3x
    return Math.ceil(duration * factor) + 's';
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="sm"
      fullWidth
      PaperProps={{
        sx: {
          borderRadius: '16px',
          border: '2px solid #ffd600',
          boxShadow: '0 8px 32px rgba(211, 47, 47, 0.2)',
        },
      }}
    >
      <DialogTitle
        sx={{
          bgcolor: '#d32f2f',
          color: '#fff',
          fontWeight: 800,
          display: 'flex',
          alignItems: 'center',
          gap: 1,
        }}
      >
        <RecordVoiceOver />
        TRANSCRIBE AUDIO
      </DialogTitle>

      <DialogContent sx={{ mt: 3 }}>
        {/* File Info */}
        <Paper
          elevation={0}
          sx={{
            p: 2,
            mb: 3,
            bgcolor: 'rgba(25, 118, 210, 0.05)',
            borderRadius: '12px',
            border: '1px solid rgba(25, 118, 210, 0.2)',
          }}
        >
          <Typography variant="body2" color="text.secondary">
            File
          </Typography>
          <Typography variant="h6" fontWeight={700} color="#1976d2">
            {filename}
          </Typography>
          {duration && (
            <Typography variant="caption" color="text.secondary">
              Duration: {Math.floor(duration / 60)}:{Math.floor(duration % 60).toString().padStart(2, '0')}
            </Typography>
          )}
        </Paper>

        {/* Options */}
        <Typography variant="subtitle1" fontWeight={700} color="#d32f2f" mb={2}>
          OPTIONS
        </Typography>

        {/* Speaker Diarization */}
        <Paper
          elevation={0}
          sx={{
            p: 2,
            mb: 2,
            bgcolor: 'rgba(67, 160, 71, 0.05)',
            borderRadius: '12px',
            border: '1px solid rgba(67, 160, 71, 0.2)',
          }}
        >
          <Box display="flex" alignItems="center" gap={1} mb={1}>
            <RecordVoiceOver sx={{ color: '#43a047' }} />
            <Typography variant="subtitle2" fontWeight={700}>
              SPEAKER DIARIZATION
            </Typography>
          </Box>

          <FormControlLabel
            control={
              <Checkbox
                checked={enableDiarization}
                onChange={(e) => setEnableDiarization(e.target.checked)}
                sx={{
                  color: '#43a047',
                  '&.Mui-checked': { color: '#43a047' },
                }}
              />
            }
            label="Enable (detect multiple speakers)"
          />

          {enableDiarization && (
            <FormControl fullWidth sx={{ mt: 1 }}>
              <Typography variant="caption" color="text.secondary" mb={0.5}>
                Method:
              </Typography>
              <Select
                value={diarizationMethod}
                onChange={(e) => setDiarizationMethod(e.target.value)}
                size="small"
                sx={{
                  borderRadius: '8px',
                  '& .MuiOutlinedInput-notchedOutline': {
                    borderColor: '#43a047',
                  },
                }}
              >
                <MenuItem value="pyannote">
                  <Box>
                    <Typography fontWeight={600}>Pyannote</Typography>
                    <Typography variant="caption" color="text.secondary">
                      Best quality, most accurate
                    </Typography>
                  </Box>
                </MenuItem>
                <MenuItem value="simple_vad">
                  <Box>
                    <Typography fontWeight={600}>SimpleVAD</Typography>
                    <Typography variant="caption" color="text.secondary">
                      Faster, good for quick analysis
                    </Typography>
                  </Box>
                </MenuItem>
                <MenuItem value="none">
                  <Box>
                    <Typography fontWeight={600}>None</Typography>
                    <Typography variant="caption" color="text.secondary">
                      Single speaker, fastest
                    </Typography>
                  </Box>
                </MenuItem>
              </Select>
            </FormControl>
          )}
        </Paper>

        {/* Fast Mode */}
        <Paper
          elevation={0}
          sx={{
            p: 2,
            bgcolor: 'rgba(255, 214, 0, 0.1)',
            borderRadius: '12px',
            border: '1px solid rgba(255, 214, 0, 0.4)',
          }}
        >
          <Box display="flex" alignItems="center" gap={1} mb={1}>
            <Speed sx={{ color: '#ffd600' }} />
            <Typography variant="subtitle2" fontWeight={700}>
              PROCESSING MODE
            </Typography>
          </Box>

          <FormControlLabel
            control={
              <Checkbox
                checked={fastMode}
                onChange={(e) => setFastMode(e.target.checked)}
                sx={{
                  color: '#ffd600',
                  '&.Mui-checked': { color: '#ffd600' },
                }}
              />
            }
            label={
              <Box>
                <Typography variant="body2" fontWeight={600}>
                  Fast Mode
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  ~10x faster, skip heavy post-processing
                </Typography>
              </Box>
            }
          />
        </Paper>

        <Divider sx={{ my: 2 }} />

        {/* Estimate */}
        <Box
          sx={{
            p: 2,
            bgcolor: 'rgba(211, 47, 47, 0.05)',
            borderRadius: '12px',
            textAlign: 'center',
          }}
        >
          <Typography variant="caption" color="text.secondary">
            ⏱️ Estimated time:
          </Typography>
          <Typography variant="h5" fontWeight={800} color="#d32f2f">
            {estimateTime()}
          </Typography>
        </Box>
      </DialogContent>

      <DialogActions sx={{ p: 3, gap: 2 }}>
        <Button
          onClick={onClose}
          variant="outlined"
          startIcon={<Close />}
          sx={{
            borderColor: '#757575',
            color: '#757575',
            textTransform: 'none',
            fontWeight: 600,
            borderRadius: '8px',
          }}
        >
          Cancel
        </Button>
        <Button
          onClick={handleConfirm}
          variant="contained"
          startIcon={<RecordVoiceOver />}
          sx={{
            bgcolor: '#d32f2f',
            color: '#fff',
            fontWeight: 700,
            textTransform: 'none',
            borderRadius: '8px',
            border: '2px solid #ffd600',
            boxShadow: '0 4px 12px rgba(211, 47, 47, 0.3)',
            '&:hover': {
              bgcolor: '#b71c1c',
              boxShadow: '0 6px 20px rgba(211, 47, 47, 0.5)',
            },
          }}
        >
          Start Transcribe
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export default TranscribeDialog;