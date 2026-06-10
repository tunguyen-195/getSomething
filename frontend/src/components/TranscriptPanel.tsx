import React, { useEffect, useState } from 'react';
import { Box, Typography, CircularProgress, IconButton, Button, Tooltip } from '@mui/material';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import DownloadIcon from '@mui/icons-material/Download';
import AnimationIcon from '@mui/icons-material/GraphicEq'; // SVG animation placeholder
import { apiFetch } from '../api/client';

interface TranscriptPanelProps {
  fileId: string;
}

// Helper lấy API base URL
const API_BASE_URL = typeof window !== 'undefined' && (window as any).API_BASE_URL ? (window as any).API_BASE_URL : '';

const TranscriptPanel: React.FC<TranscriptPanelProps> = ({ fileId }) => {
  const [transcript, setTranscript] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    setLoading(true);
    setError(null);
    setTranscript(null);
    // Use correct route: /api/v1/audio/files/{file_id}/transcript
    apiFetch(`${API_BASE_URL}/api/v1/audio/files/${fileId}/transcript`)
      .then(res => {
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
        return res.json();
      })
      .then(data => {
        // Extract transcript from response (check multiple locations for compatibility)
        // Priority: data.transcript > data.result.transcription > data.result.text
        let transcriptText = null;
        if (data.transcript) {
          transcriptText = data.transcript;
        } else if (data.result) {
          if (typeof data.result === 'object') {
            transcriptText = data.result.transcription || data.result.transcript || data.result.text;
          }
        } else if (data.transcription) {
          transcriptText = data.transcription;
        }

        setTranscript(transcriptText);
        setLoading(false);
      })
      .catch((error) => {
        console.error('Failed to load transcript:', error);
        setError('Failed to load transcript');
        setLoading(false);
      });
  }, [fileId]);

  const handleCopy = () => {
    if (transcript) {
      navigator.clipboard.writeText(transcript);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  };

  const handleDownload = () => {
    if (transcript) {
      const blob = new Blob([transcript], { type: 'text/plain' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `transcript_${fileId}.txt`;
      a.click();
      URL.revokeObjectURL(url);
    }
  };

  return (
    <Box>
      <Box display="flex" alignItems="center" mb={2}>
        <Typography variant="h6" fontWeight={700} sx={{ flexGrow: 1 }}>Transcript</Typography>
        <Tooltip title={copied ? 'Đã copy!' : 'Copy transcript'}>
          <Button
            onClick={handleCopy}
            disabled={!transcript}
            variant="outlined"
            color={copied ? 'success' : 'primary'}
            size="small"
            startIcon={<ContentCopyIcon />}
            sx={{ ml: 2 }}
          >
            {copied ? 'Đã copy' : 'Copy'}
          </Button>
        </Tooltip>
        <Tooltip title="Download">
          <span>
            <IconButton onClick={handleDownload} disabled={!transcript}><DownloadIcon /></IconButton>
          </span>
        </Tooltip>
      </Box>
      {loading ? (
        <Box display="flex" flexDirection="column" alignItems="center" justifyContent="center" height={180}>
          <AnimationIcon sx={{ fontSize: 48, color: 'primary.main', mb: 2, animation: 'pulse 1.5s infinite' }} />
          <CircularProgress />
          <Typography mt={2}>Loading transcript...</Typography>
        </Box>
      ) : error ? (
        <Typography color="error">{error}</Typography>
      ) : transcript ? (
        <Box sx={{ whiteSpace: 'pre-wrap', bgcolor: 'background.paper', p: 2, borderRadius: 2, boxShadow: 1, minHeight: 120 }}>
          {transcript}
        </Box>
      ) : (
        <Typography color="text.secondary">No transcript available.</Typography>
      )}
    </Box>
  );
};

export default TranscriptPanel;
