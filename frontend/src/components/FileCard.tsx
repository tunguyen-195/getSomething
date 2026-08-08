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
  Visibility as ViewIcon,
} from '@mui/icons-material';
import DateTimeText from './DateTimeText';

interface FileCardProps {
  file: {
    id: string;
    audio_id?: string | number;
    filename: string;
    duration?: number;
    size?: number;
    status: 'uploaded' | 'transcribing' | 'transcribed' | 'summarizing' | 'summarized' | 'visualizing' | 'visualized' | 'failed';
    num_speakers?: number;
    has_diarization?: boolean;
    created_at?: string;
    updated_at?: string;
    uploaded_at?: string;
    transcript?: string;
    summary?: string;
    visualization_data?: any;
    has_visualization?: boolean;
    download_url?: string;
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
  const [visualizationExpanded, setVisualizationExpanded] = useState(false);

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
      case 'visualizing': return '#673ab7'; // Deep Purple
      case 'visualized': return '#3f51b5'; // Indigo
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
      case 'visualizing': return 'Visualizing...';
      case 'visualized': return 'Visualized';
      case 'failed': return 'Failed';
      default: return status;
    }
  };

  const isProcessing = file.status === 'transcribing' || file.status === 'summarizing' || file.status === 'visualizing';
  const canTranscribe = file.status === 'uploaded' || file.status === 'failed';
  // Fixed: Include 'visualized' status and check for transcript existence
  const canSummarize = ['transcribed', 'summarized', 'visualized'].includes(file.status) || !!file.transcript;
  const canVisualize = ['transcribed', 'summarized', 'visualized'].includes(file.status) || !!file.transcript;


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

  // Clean markdown để hiển thị văn bản hành chính chuẩn
  const cleanMarkdown = (text: string): string => {
    if (!text) return '';
    return text
      .replace(/^#{1,6}\s*/gm, '')           // Remove headers
      .replace(/\*\*([^*]+)\*\*/g, '$1')      // Remove bold
      .replace(/__([^_]+)__/g, '$1')
      .replace(/\*([^*]+)\*/g, '$1')          // Remove italic
      .replace(/_([^_]+)_/g, '$1')
      .replace(/^[\-\*]\s+/gm, '• ')          // Convert bullets to •
      .replace(/^(\d+)\.\s+/gm, '$1. ')       // Keep numbered lists clean
      .replace(/```[\s\S]*?```/g, '')         // Remove code blocks
      .replace(/`([^`]+)`/g, '$1')
      .replace(/^[\-\*_]{3,}$/gm, '')         // Remove horizontal rules
      .replace(/\n{3,}/g, '\n\n')             // Remove extra blank lines
      .trim();
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
        <Box display="flex" alignItems="center" gap={2} mb={2} flexWrap="wrap">
          <AudioIcon sx={{ fontSize: 40, color: '#d32f2f' }} />
          <Box flex={1} minWidth={0}>
            <Typography variant="h6" fontWeight={700} color="#23272f" sx={{ overflowWrap: 'anywhere' }}>
              {file.filename}
            </Typography>
            <Box display="flex" columnGap={2} rowGap={0.5} mt={0.5} flexWrap="wrap">
              <DateTimeText
                value={file.uploaded_at || file.created_at}
                label="Tải lên"
              />
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
              ml: { xs: 6.5, sm: 'auto' },
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

        {/* Audio Player */}
        <Box mb={2}>
          <Typography variant="subtitle2" fontWeight={700} color="#d32f2f" mb={1}>
            🎧 AUDIO PLAYER
          </Typography>
          <Box
            sx={{
              p: 1.5,
              bgcolor: 'rgba(211, 47, 47, 0.05)',
              borderRadius: '12px',
              border: '1px solid rgba(211, 47, 47, 0.2)',
            }}
          >
            <audio
              controls
              style={{ width: '100%', height: 40 }}
              src={file.download_url || `/api/v1/audio/${file.audio_id || file.id}/download`}
            >
              Your browser does not support the audio element.
            </audio>
          </Box>
        </Box>

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
              {file.has_visualization && <CheckIcon sx={{ color: '#3f51b5', fontSize: 18 }} />}
            </Box>
            <Box display="flex" gap={1} ml={4}>
              {file.status === 'visualizing' ? (
                <Box display="flex" alignItems="center" gap={1}>
                  <RefreshIcon sx={{ color: '#673ab7', animation: 'spin 1s linear infinite', '@keyframes spin': { '0%': { transform: 'rotate(0deg)' }, '100%': { transform: 'rotate(360deg)' } } }} />
                  <Typography variant="caption" color="text.secondary">
                    Generating visualization...
                  </Typography>
                </Box>
              ) : canVisualize ? (
                <>
                  <Button
                    variant={file.has_visualization ? "outlined" : "contained"}
                    size="small"
                    startIcon={file.has_visualization ? <RefreshIcon /> : <VisualizeIcon />}
                    onClick={onVisualize}
                    sx={{
                      bgcolor: file.has_visualization ? 'transparent' : '#9c27b0',
                      color: file.has_visualization ? '#9c27b0' : '#fff',
                      borderColor: '#9c27b0',
                      fontWeight: 700,
                      borderRadius: '8px',
                      textTransform: 'none',
                      '&:hover': {
                        bgcolor: file.has_visualization ? 'rgba(156, 39, 176, 0.08)' : '#7b1fa2',
                        borderColor: '#7b1fa2',
                      },
                    }}
                  >
                    {file.has_visualization ? 'Re-generate' : 'Generate'}
                  </Button>
                  {file.has_visualization && (
                    <Typography variant="caption" color="success.main" sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                      ✓ Ready
                    </Typography>
                  )}
                </>
              ) : (
                <Typography variant="caption" color="text.secondary">
                  ⏳ Transcribe first
                </Typography>
              )}
            </Box>
          </Box>
        </Box>

        <Divider sx={{ my: 2, borderColor: 'rgba(255, 214, 0, 0.3)' }} />

        {/* VIEW RESULTS Section - Appears after completion */}
        {(file.transcript || file.summary) && (
          <Box mb={3}>
            <Typography
              variant="subtitle2"
              fontWeight={700}
              color="#43a047"
              mb={1.5}
              sx={{ letterSpacing: 0.5 }}
            >
              👁️ VIEW RESULTS
            </Typography>
            <Box display="flex" gap={1.5} flexWrap="wrap">
              {file.transcript && (
                <Button
                  variant="outlined"
                  startIcon={<ViewIcon />}
                  onClick={() => setTranscriptExpanded(!transcriptExpanded)}
                  sx={{
                    borderColor: '#43a047',
                    color: '#43a047',
                    fontWeight: 700,
                    borderRadius: '12px',
                    borderWidth: '2.5px',
                    px: 2.5,
                    py: 1,
                    fontSize: '0.9rem',
                    textTransform: 'none',
                    '&:hover': {
                      borderWidth: '2.5px',
                      bgcolor: 'rgba(67, 160, 71, 0.1)',
                      transform: 'scale(1.05)',
                      boxShadow: '0 4px 16px rgba(67, 160, 71, 0.3)',
                    },
                    transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
                    animation: 'fadeInUp 0.5s ease-out',
                    '@keyframes fadeInUp': {
                      from: { opacity: 0, transform: 'translateY(10px)' },
                      to: { opacity: 1, transform: 'translateY(0)' },
                    },
                  }}
                >
                  📝 View Transcript
                </Button>
              )}

              {file.summary && (
                <Button
                  variant="outlined"
                  startIcon={<ViewIcon />}
                  onClick={() => setSummaryExpanded(!summaryExpanded)}
                  sx={{
                    borderColor: '#ff9800',
                    color: '#ff9800',
                    fontWeight: 700,
                    borderRadius: '12px',
                    borderWidth: '2.5px',
                    px: 2.5,
                    py: 1,
                    fontSize: '0.9rem',
                    textTransform: 'none',
                    '&:hover': {
                      borderWidth: '2.5px',
                      bgcolor: 'rgba(255, 152, 0, 0.1)',
                      transform: 'scale(1.05)',
                      boxShadow: '0 4px 16px rgba(255, 152, 0, 0.3)',
                    },
                    transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
                    animation: 'fadeInUp 0.5s ease-out 0.1s',
                    animationFillMode: 'both',
                  }}
                >
                  📊 View Summary
                </Button>
              )}

              {file.has_visualization && (
                <Button
                  variant="outlined"
                  startIcon={<ViewIcon />}
                  onClick={() => setVisualizationExpanded(!visualizationExpanded)}
                  sx={{
                    borderColor: '#3f51b5',
                    color: '#3f51b5',
                    fontWeight: 700,
                    borderRadius: '12px',
                    borderWidth: '2.5px',
                    px: 2.5,
                    py: 1,
                    fontSize: '0.9rem',
                    textTransform: 'none',
                    '&:hover': {
                      borderWidth: '2.5px',
                      bgcolor: 'rgba(63, 81, 181, 0.1)',
                      transform: 'scale(1.05)',
                      boxShadow: '0 4px 16px rgba(63, 81, 181, 0.3)',
                    },
                    transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
                    animation: 'fadeInUp 0.5s ease-out 0.2s',
                    animationFillMode: 'both',
                  }}
                >
                  📈 View Visualization
                </Button>
              )}
            </Box>
          </Box>
        )}

        {/* Delete Button */}
        <Box display="flex" justifyContent="flex-end" mb={2}>
          <IconButton
            size="small"
            onClick={onDelete}
            sx={{
              color: '#d32f2f',
              '&:hover': {
                bgcolor: 'rgba(211, 47, 47, 0.1)',
                transform: 'rotate(10deg)',
              },
              transition: 'all 0.3s',
            }}
          >
            <DeleteIcon />
          </IconButton>
        </Box>

        <Divider sx={{ my: 2, borderColor: 'rgba(67, 160, 71, 0.3)' }} />

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
                  {cleanMarkdown(file.summary || '')}
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
