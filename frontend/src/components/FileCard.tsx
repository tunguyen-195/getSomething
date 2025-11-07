import React, { useState } from 'react';
import {
  Card,
  CardContent,
  Typography,
  Box,
  Button,
  Chip,
  LinearProgress,
  IconButton,
  Collapse,
  Divider,
} from '@mui/material';
import {
  MusicNote as AudioIcon,
  RecordVoiceOver as TranscribeIcon,
  Description as SummaryIcon,
  Timeline as VisualizeIcon,
  Delete as DeleteIcon,
  ExpandMore as ExpandMoreIcon,
  Settings as SettingsIcon,
  Refresh as RefreshIcon,
  CheckCircle as CheckIcon,
  ContentCopy as ContentCopyIcon,
} from '@mui/icons-material';

interface FileCardProps {
  file: {
    id: string;
    filename: string;
    duration?: number;
    size?: number;
    status: 'uploaded' | 'transcribing' | 'transcribed' | 'summarizing' | 'summarized' | 'failed';
    num_speakers?: number;
    has_diarization?: boolean;
    created_at?: string;
    transcript?: string;
    summary?: string;
  };
  onTranscribe: () => void;
  onSummarize: () => void;
  onVisualize: () => void;
  onDelete: () => void;
  onViewTranscript: () => void;
}

const FileCard: React.FC<FileCardProps> = ({
  file,
  onTranscribe,
  onSummarize,
  onVisualize,
  onDelete,
  onViewTranscript,
}) => {
  const [expanded, setExpanded] = useState(false);
  const [transcriptExpanded, setTranscriptExpanded] = useState(false);
  const [summaryExpanded, setSummaryExpanded] = useState(false);
  
  const [copiedTranscript, setCopiedTranscript] = useState(false);
  const [copiedSummary, setCopiedSummary] = useState(false);

  const handleCopyTranscript = () => {
    if (file.transcript) {
      navigator.clipboard.writeText(file.transcript);
      setCopiedTranscript(true);
      setTimeout(() => setCopiedTranscript(false), 2000);
    }
  };

  const handleCopySummary = () => {
    if (file.summary) {
      navigator.clipboard.writeText(file.summary);
      setCopiedSummary(true);
      setTimeout(() => setCopiedSummary(false), 2000);
    }
  };

  // Status colors (Cherry2 theme)
  const getStatusColor = (status: string) => {
    switch (status) {
      case 'uploaded': return '#1976d2'; // Blue
      case 'transcribing': return '#ffd600'; // Yellow
      case 'transcribed': return '#43a047'; // Green
      case 'summarizing': return '#ff9800'; // Orange
      case 'summarized': return '#9c27b0'; // Purple
      case 'failed': return '#d32f2f'; // Red
      default: return '#757575';
    }
  };

  const getStatusLabel = (status: string) => {
    switch (status) {
      case 'uploaded': return 'Uploaded';
      case 'transcribing': return 'Transcribing...';
      case 'transcribed': return 'Transcribed';
      case 'summarizing': return 'Summarizing...';
      case 'summarized': return 'Summarized';
      case 'failed': return 'Failed';
      default: return status;
    }
  };

  const isProcessing = file.status === 'transcribing' || file.status === 'summarizing';
  const canTranscribe = file.status === 'uploaded' || file.status === 'failed';
  const canSummarize = file.status === 'transcribed' || file.status === 'summarized';
  const canVisualize = file.status === 'transcribed' || file.status === 'summarized';

  const formatDuration = (seconds?: number) => {
    if (!seconds) return 'N/A';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const formatSize = (bytes?: number) => {
    if (!bytes) return 'N/A';
    return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
  };

  return (
    <Card
      sx={{
        borderRadius: '16px',
        boxShadow: '0 4px 24px rgba(211, 47, 47, 0.08)',
        border: `2px solid ${isProcessing ? '#ffd600' : 'rgba(255, 214, 0, 0.3)'}`,
        transition: 'all 0.3s',
        '&:hover': {
          boxShadow: '0 8px 32px rgba(211, 47, 47, 0.15)',
          transform: 'translateY(-4px)',
        },
      }}
    >
      <CardContent>
        {/* Header */}
        <Box display="flex" alignItems="center" gap={2} mb={2}>
          <AudioIcon sx={{ fontSize: 40, color: '#d32f2f' }} />
          <Box flex={1}>
            <Typography variant="h6" fontWeight={700} color="#23272f">
              {file.filename}
            </Typography>
            <Box display="flex" gap={2} mt={0.5}>
              <Typography variant="caption" color="text.secondary">
                ⏱️ {formatDuration(file.duration)}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                💾 {formatSize(file.size)}
              </Typography>
              {file.num_speakers && (
                <Typography variant="caption" color="text.secondary">
                  👥 {file.num_speakers} speakers
                </Typography>
              )}
            </Box>
          </Box>
          <Chip
            label={getStatusLabel(file.status)}
            sx={{
              bgcolor: getStatusColor(file.status),
              color: '#fff',
              fontWeight: 700,
              boxShadow: `0 2px 8px ${getStatusColor(file.status)}40`,
            }}
          />
        </Box>

        {/* Progress bar for processing */}
        {isProcessing && (
          <LinearProgress
            sx={{
              mb: 2,
              height: 6,
              borderRadius: 3,
              bgcolor: 'rgba(255, 214, 0, 0.2)',
              '& .MuiLinearProgress-bar': {
                bgcolor: '#ffd600',
              },
            }}
          />
        )}

        <Divider sx={{ my: 2, borderColor: 'rgba(255, 214, 0, 0.3)' }} />

        {/* Actions Section */}
        <Box>
          <Typography variant="subtitle2" fontWeight={700} color="#d32f2f" mb={1.5}>
            ACTIONS
          </Typography>

          {/* Transcribe Action */}
          <Box mb={2}>
            <Box display="flex" alignItems="center" gap={1} mb={0.5}>
              <TranscribeIcon sx={{ color: '#1976d2' }} />
              <Typography variant="body2" fontWeight={600}>
                Transcribe
              </Typography>
              {file.status === 'transcribed' && <CheckIcon sx={{ color: '#43a047', fontSize: 18 }} />}
            </Box>
            <Box display="flex" gap={1} ml={4}>
              {canTranscribe ? (
                <Button
                  variant="contained"
                  size="small"
                  startIcon={<TranscribeIcon />}
                  onClick={onTranscribe}
                  sx={{
                    bgcolor: '#d32f2f',
                    color: '#fff',
                    fontWeight: 700,
                    borderRadius: '8px',
                    textTransform: 'none',
                    border: '2px solid #ffd600',
                    '&:hover': { bgcolor: '#b71c1c' },
                  }}
                >
                  Start Transcribe
                </Button>
              ) : file.status === 'transcribing' ? (
                <Typography variant="caption" color="text.secondary">
                  ⏳ Processing...
                </Typography>
              ) : (
                <>
                  <Typography variant="caption" color="success.main">
                    ✅ Done {file.has_diarization && `(${file.num_speakers} speakers)`}
                  </Typography>
                  <Button
                    size="small"
                    startIcon={<SettingsIcon />}
                    onClick={onTranscribe}
                    sx={{ textTransform: 'none', fontSize: 11 }}
                  >
                    Re-run
                  </Button>
                </>
              )}
            </Box>
          </Box>

          {/* Summarize Action */}
          <Box mb={2}>
            <Box display="flex" alignItems="center" gap={1} mb={0.5}>
              <SummaryIcon sx={{ color: '#ff9800' }} />
              <Typography variant="body2" fontWeight={600}>
                Summarize
              </Typography>
              {file.status === 'summarized' && <CheckIcon sx={{ color: '#9c27b0', fontSize: 18 }} />}
            </Box>
            <Box display="flex" gap={1} ml={4}>
              {canSummarize ? (
                <Button
                  variant="contained"
                  size="small"
                  startIcon={<SummaryIcon />}
                  onClick={onSummarize}
                  disabled={!file.transcript}
                  sx={{
                    bgcolor: '#ff9800',
                    color: '#fff',
                    fontWeight: 700,
                    borderRadius: '8px',
                    textTransform: 'none',
                    '&:hover': { bgcolor: '#f57c00' },
                  }}
                >
                  Start Summary
                </Button>
              ) : file.status === 'summarizing' ? (
                <Typography variant="caption" color="text.secondary">
                  ⏳ Summarizing...
                </Typography>
              ) : (
                <Typography variant="caption" color="text.secondary">
                  ⏳ Transcribe first
                </Typography>
              )}
            </Box>
          </Box>

          {/* Visualize Action */}
          <Box>
            <Box display="flex" alignItems="center" gap={1} mb={0.5}>
              <VisualizeIcon sx={{ color: '#9c27b0' }} />
              <Typography variant="body2" fontWeight={600}>
                Visualize
              </Typography>
            </Box>
            <Box display="flex" gap={1} ml={4}>
              {canVisualize ? (
                <Button
                  variant="outlined"
                  size="small"
                  startIcon={<VisualizeIcon />}
                  onClick={onVisualize}
                  sx={{
                    color: '#9c27b0',
                    borderColor: '#9c27b0',
                    fontWeight: 700,
                    borderRadius: '8px',
                    textTransform: 'none',
                    '&:hover': {
                      bgcolor: 'rgba(156, 39, 176, 0.08)',
                      borderColor: '#7b1fa2',
                    },
                  }}
                >
                  Generate
                </Button>
              ) : (
                <Typography variant="caption" color="text.secondary">
                  ⏳ Transcribe first
                </Typography>
              )}
            </Box>
          </Box>
        </Box>

        <Divider sx={{ my: 2, borderColor: 'rgba(255, 214, 0, 0.3)' }} />

        {/* Bottom Actions */}
        <Box display="flex" justifyContent="space-between" alignItems="center">
          <Button
            size="small"
            onClick={onViewTranscript}
            disabled={!file.transcript}
            sx={{
              color: '#1976d2',
              textTransform: 'none',
              fontWeight: 600,
            }}
          >
            🔽 View Transcript
          </Button>
          <IconButton size="small" onClick={onDelete} sx={{ color: '#d32f2f' }}>
            <DeleteIcon />
          </IconButton>
        </Box>

        {/* Transcript Section - Inline Display */}
        {file.transcript && (
          <Box mt={3}>
            <Box display="flex" alignItems="center" justifyContent="space-between" mb={1} px={1}>
              <Box display="flex" alignItems="center" gap={1}>
                <TranscribeIcon sx={{ color: '#43a047', fontSize: 24 }} />
                <Typography variant="h6" fontWeight={700} color="#43a047">
                  📝 Transcript Result
                </Typography>
              </Box>
              <Box display="flex" gap={1}>
                <Button
                  size="small"
                  variant={copiedTranscript ? "contained" : "outlined"}
                  onClick={handleCopyTranscript}
                  sx={{ 
                    borderRadius: '8px',
                    bgcolor: copiedTranscript ? '#43a047' : undefined,
                    color: copiedTranscript ? '#fff' : '#43a047',
                    borderColor: '#43a047'
                  }}
                >
                  {copiedTranscript ? '✓ Copied!' : '📋 Copy'}
                </Button>
                <IconButton 
                  size="small"
                  onClick={() => setTranscriptExpanded(!transcriptExpanded)}
                  sx={{
                    transform: transcriptExpanded ? 'rotate(180deg)' : 'rotate(0deg)',
                    transition: 'transform 0.3s',
                    color: '#43a047'
                  }}
                >
                  <ExpandMoreIcon />
                </IconButton>
              </Box>
            </Box>
            <Collapse in={transcriptExpanded}>
              <Box
                sx={{
                  bgcolor: 'rgba(67, 160, 71, 0.05)',
                  p: 2.5,
                  borderRadius: '12px',
                  border: '2px solid rgba(67, 160, 71, 0.3)',
                  maxHeight: '500px',
                  overflow: 'auto',
                  boxShadow: 'inset 0 2px 8px rgba(0,0,0,0.05)',
                }}
              >
                <Typography
                  variant="body1"
                  sx={{
                    whiteSpace: 'pre-wrap',
                    lineHeight: 1.9,
                    color: '#23272f',
                    fontSize: '0.95rem',
                  }}
                >
                  {file.transcript}
                </Typography>
              </Box>
            </Collapse>
            {!transcriptExpanded && (
              <Typography 
                variant="body2" 
                color="text.secondary"
                sx={{ 
                  mt: 1,
                  px: 1,
                  fontStyle: 'italic',
                  cursor: 'pointer',
                  transition: 'all 0.2s',
                  '&:hover': { color: '#43a047', textDecoration: 'underline' }
                }}
                onClick={() => setTranscriptExpanded(true)}
              >
                👆 Click to expand transcript... ({file.transcript.length} chars)
              </Typography>
            )}
          </Box>
        )}

        {/* Summary Section - Inline Display */}
        {file.summary && (
          <Box mt={3}>
            <Box display="flex" alignItems="center" justifyContent="space-between" mb={1} px={1}>
              <Box display="flex" alignItems="center" gap={1}>
                <SummaryIcon sx={{ color: '#ff9800', fontSize: 24 }} />
                <Typography variant="h6" fontWeight={700} color="#ff9800">
                  📊 Summary Result
                </Typography>
              </Box>
              <Box display="flex" gap={1}>
                <Button
                  size="small"
                  variant={copiedSummary ? "contained" : "outlined"}
                  onClick={handleCopySummary}
                  sx={{ 
                    borderRadius: '8px',
                    bgcolor: copiedSummary ? '#ff9800' : undefined,
                    color: copiedSummary ? '#fff' : '#ff9800',
                    borderColor: '#ff9800'
                  }}
                >
                  {copiedSummary ? '✓ Copied!' : '📋 Copy'}
                </Button>
                <IconButton 
                  size="small"
                  onClick={() => setSummaryExpanded(!summaryExpanded)}
                  sx={{
                    transform: summaryExpanded ? 'rotate(180deg)' : 'rotate(0deg)',
                    transition: 'transform 0.3s',
                    color: '#ff9800'
                  }}
                >
                  <ExpandMoreIcon />
                </IconButton>
              </Box>
            </Box>
            <Collapse in={summaryExpanded}>
              <Box
                sx={{
                  bgcolor: 'rgba(255, 152, 0, 0.05)',
                  p: 2.5,
                  borderRadius: '12px',
                  border: '2px solid rgba(255, 152, 0, 0.3)',
                  maxHeight: '500px',
                  overflow: 'auto',
                  boxShadow: 'inset 0 2px 8px rgba(0,0,0,0.05)',
                }}
              >
                <Typography
                  variant="body1"
                  sx={{
                    whiteSpace: 'pre-wrap',
                    lineHeight: 1.9,
                    color: '#23272f',
                    fontSize: '0.95rem',
                  }}
                >
                  {file.summary}
                </Typography>
              </Box>
            </Collapse>
            {!summaryExpanded && (
              <Typography 
                variant="body2" 
                color="text.secondary"
                sx={{ 
                  mt: 1,
                  px: 1,
                  fontStyle: 'italic',
                  cursor: 'pointer',
                  transition: 'all 0.2s',
                  '&:hover': { color: '#ff9800', textDecoration: 'underline' }
                }}
                onClick={() => setSummaryExpanded(true)}
              >
                👆 Click to expand summary... ({file.summary.length} chars)
              </Typography>
            )}
          </Box>
        )}
      </CardContent>
    </Card>
  );
};

export default FileCard;