import React, { useEffect, useState } from 'react';
import { Box, Typography, CircularProgress, IconButton, Button, Tooltip } from '@mui/material';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import DownloadIcon from '@mui/icons-material/Download';
import AnimationIcon from '@mui/icons-material/GraphicEq'; // SVG animation placeholder

interface TranscriptPanelProps {
  fileId: string;
}

const TranscriptPanel: React.FC<TranscriptPanelProps> = ({ fileId }) => {
  const [transcript, setTranscript] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    setLoading(true);
    setError(null);
    setTranscript(null);
    fetch(`http://localhost:8000/api/v1/files/${fileId}/transcript`)
      .then(res => res.json())
      .then(data => {
        if (data.result && (data.result.transcription || data.result.text)) {
          setTranscript(data.result.transcription || data.result.text);
        } else if (data.transcription) {
          setTranscript(data.transcription);
        } else if (data.transcript) {
          setTranscript(data.transcript);
        } else {
          setTranscript(null);
        }
        setLoading(false);
      })
      .catch(() => {
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
        <Tooltip title="Copy">
          <span>
            <IconButton onClick={handleCopy} disabled={!transcript}><ContentCopyIcon color={copied ? 'success' : 'inherit'} /></IconButton>
          </span>
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