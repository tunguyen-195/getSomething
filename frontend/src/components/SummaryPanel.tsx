import React, { useState } from 'react';
import {
  Box,
  Typography,
  Paper,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Button,
  IconButton,
  Chip,
  Divider,
  CircularProgress,
} from '@mui/material';
import {
  ExpandMore as ExpandMoreIcon,
  ContentCopy as ContentCopyIcon,
  Description as SummaryIcon,
  CheckCircle as CheckIcon,
  Download as DownloadIcon,
} from '@mui/icons-material';

interface FileWithSummary {
  task_id: string;
  filename: string;
  summary?: string;
  status: string;
  num_speakers?: number;
}

interface SummaryPanelProps {
  files: FileWithSummary[];
  caseId: string;
  mode?: 'light' | 'dark';
}

const SummaryPanel: React.FC<SummaryPanelProps> = ({ files, caseId, mode = 'light' }) => {
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  const filesWithSummary = files.filter(f => f.summary);
  const pendingFiles = files.filter(f => !f.summary && f.status !== 'uploaded');

  const handleCopy = (taskId: string, summary: string) => {
    navigator.clipboard.writeText(summary);
    setCopiedId(taskId);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const handleExportAll = () => {
    if (filesWithSummary.length === 0) return;

    setExporting(true);
    const content = filesWithSummary
      .map((f, idx) => `## File ${idx + 1}: ${f.filename}\n\n${f.summary}\n`)
      .join('\n---\n\n');

    const blob = new Blob([content], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `case_${caseId}_summaries.md`;
    a.click();
    URL.revokeObjectURL(url);
    setExporting(false);
  };

  const highlightKeywords = (text: string) => {
    const keywords = /(người|địa điểm|thời gian|quyết định|hành động|cảm xúc|chủ đề|thực thể|sự kiện|vai trò|tên|số điện thoại|email|địa chỉ)/gi;
    const parts = text.split(keywords);
    return parts.map((part, i) =>
      keywords.test(part)
        ? <strong key={i} style={{ color: '#d32f2f' }}>{part}</strong>
        : part
    );
  };

  // Clean markdown để hiển thị văn bản hành chính chuẩn
  const cleanMarkdown = (text: string): string => {
    if (!text) return '';
    return text
      // Remove headers (###, ##, #)
      .replace(/^#{1,6}\s*/gm, '')
      // Remove bold (**text** or __text__)
      .replace(/\*\*([^*]+)\*\*/g, '$1')
      .replace(/__([^_]+)__/g, '$1')
      // Remove italic (*text* or _text_)
      .replace(/\*([^*]+)\*/g, '$1')
      .replace(/_([^_]+)_/g, '$1')
      // Remove bullet points (- or *)
      .replace(/^[\-\*]\s+/gm, '• ')
      // Remove numbered lists styling but keep numbers
      .replace(/^(\d+)\.\s+/gm, '$1. ')
      // Remove code blocks
      .replace(/```[\s\S]*?```/g, '')
      .replace(/`([^`]+)`/g, '$1')
      // Remove horizontal rules
      .replace(/^[\-\*_]{3,}$/gm, '')
      // Remove extra blank lines
      .replace(/\n{3,}/g, '\n\n')
      // Trim
      .trim();
  };

  if (files.length === 0) {
    return (
      <Paper sx={{ p: 4, textAlign: 'center', borderRadius: '16px' }}>
        <SummaryIcon sx={{ fontSize: 64, color: '#bdbdbd', mb: 2 }} />
        <Typography variant="h6" color="text.secondary">
          No files uploaded yet
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Upload audio files and run summarization to see results here
        </Typography>
      </Paper>
    );
  }

  if (filesWithSummary.length === 0) {
    return (
      <Paper sx={{ p: 4, textAlign: 'center', borderRadius: '16px' }}>
        <SummaryIcon sx={{ fontSize: 64, color: '#ff9800', mb: 2 }} />
        <Typography variant="h6" color="text.secondary">
          No summaries available yet
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Transcribe your files first, then run "Summarize" to generate summaries
        </Typography>
        {pendingFiles.length > 0 && (
          <Chip
            label={`${pendingFiles.length} file(s) processing...`}
            color="warning"
            sx={{ mt: 1 }}
          />
        )}
      </Paper>
    );
  }

  return (
    <Box>
      {/* Header with Export Button */}
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Box display="flex" alignItems="center" gap={1}>
          <SummaryIcon sx={{ color: '#ff9800', fontSize: 28 }} />
          <Typography variant="h6" fontWeight={700}>
            Case Summaries
          </Typography>
          <Chip
            label={`${filesWithSummary.length} file(s)`}
            size="small"
            sx={{ ml: 1, bgcolor: '#ff9800', color: '#fff' }}
          />
        </Box>
        <Button
          variant="contained"
          startIcon={exporting ? <CircularProgress size={16} color="inherit" /> : <DownloadIcon />}
          onClick={handleExportAll}
          disabled={exporting}
          sx={{
            bgcolor: '#ff9800',
            '&:hover': { bgcolor: '#f57c00' },
            borderRadius: '12px',
            textTransform: 'none',
            fontWeight: 600,
          }}
        >
          Export All
        </Button>
      </Box>

      {/* Summary Accordions */}
      {filesWithSummary.map((file, idx) => (
        <Accordion
          key={file.task_id}
          defaultExpanded={idx === 0}
          sx={{
            mb: 2,
            borderRadius: '12px !important',
            border: '1px solid rgba(255, 152, 0, 0.3)',
            '&:before': { display: 'none' },
            boxShadow: '0 2px 8px rgba(255, 152, 0, 0.1)',
          }}
        >
          <AccordionSummary
            expandIcon={<ExpandMoreIcon />}
            sx={{
              bgcolor: 'rgba(255, 152, 0, 0.05)',
              borderRadius: '12px 12px 0 0',
            }}
          >
            <Box display="flex" alignItems="center" gap={2} width="100%">
              <Typography fontWeight={600} flex={1}>
                📄 {file.filename}
              </Typography>
              {file.num_speakers && (
                <Chip
                  label={`${file.num_speakers} speakers`}
                  size="small"
                  variant="outlined"
                />
              )}
              <Chip
                icon={<CheckIcon sx={{ fontSize: 16 }} />}
                label="Summarized"
                size="small"
                color="success"
              />
            </Box>
          </AccordionSummary>
          <AccordionDetails sx={{ pt: 2 }}>
            {/* Copy Button */}
            <Box display="flex" justifyContent="flex-end" mb={2}>
              <Button
                size="small"
                variant={copiedId === file.task_id ? 'contained' : 'outlined'}
                startIcon={<ContentCopyIcon />}
                onClick={() => handleCopy(file.task_id, file.summary || '')}
                sx={{
                  borderRadius: '8px',
                  textTransform: 'none',
                  bgcolor: copiedId === file.task_id ? '#4caf50' : undefined,
                  color: copiedId === file.task_id ? '#fff' : '#ff9800',
                  borderColor: '#ff9800',
                  '&:hover': {
                    bgcolor: copiedId === file.task_id ? '#43a047' : 'rgba(255, 152, 0, 0.1)',
                  },
                }}
              >
                {copiedId === file.task_id ? '✓ Copied!' : 'Copy'}
              </Button>
            </Box>

            {/* Summary Content */}
            <Paper
              sx={{
                p: 3,
                bgcolor: 'rgba(255, 152, 0, 0.03)',
                borderRadius: '12px',
                border: '1px solid rgba(255, 152, 0, 0.2)',
              }}
            >
              <Typography
                variant="body1"
                sx={{
                  whiteSpace: 'pre-wrap',
                  lineHeight: 1.8,
                  fontSize: '0.95rem',
                }}
              >
                {highlightKeywords(cleanMarkdown(file.summary || ''))}
              </Typography>
            </Paper>
          </AccordionDetails>
        </Accordion>
      ))}

      {/* Pending Files Notice */}
      {pendingFiles.length > 0 && (
        <>
          <Divider sx={{ my: 3 }} />
          <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
            ⏳ Pending Summarization ({pendingFiles.length} files)
          </Typography>
          <Box display="flex" flexWrap="wrap" gap={1}>
            {pendingFiles.map(f => (
              <Chip
                key={f.task_id}
                label={f.filename}
                size="small"
                variant="outlined"
                color="warning"
              />
            ))}
          </Box>
        </>
      )}
    </Box>
  );
};

export default SummaryPanel;
