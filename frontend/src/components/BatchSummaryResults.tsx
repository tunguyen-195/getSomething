import React, { useMemo, useState } from 'react';
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Typography,
} from '@mui/material';
import {
  CheckCircle as CheckCircleIcon,
  ContentCopy as ContentCopyIcon,
  ErrorOutline as ErrorOutlineIcon,
  ExpandMore as ExpandMoreIcon,
} from '@mui/icons-material';
import type { AudioBatchSummaryJob } from '../api/client';
import {
  BATCH_SUMMARY_TYPE_DESCRIPTIONS,
  BATCH_SUMMARY_TYPE_LABELS,
  hasUsableBatchSummaryResult,
  normalizeBatchSummaryResults,
} from '../utils/batchSummary';

interface BatchSummaryResultsProps {
  job: AudioBatchSummaryJob;
  /** Keep the source manifest visible next to every independently persisted result. */
  showSources?: boolean;
}

const BatchSummaryResults: React.FC<BatchSummaryResultsProps> = ({ job, showSources = false }) => {
  const [copiedType, setCopiedType] = useState<string | null>(null);
  const results = useMemo(() => normalizeBatchSummaryResults(job), [job]);

  const copyResult = async (type: string, text: string) => {
    await navigator.clipboard?.writeText(text);
    setCopiedType(type);
    window.setTimeout(() => setCopiedType(current => current === type ? null : current), 1500);
  };

  if (results.length === 0) {
    return (
      <Alert severity="info" data-testid="batch-summary-empty">
        Chưa có kết quả summary theo loại. Hãy kiểm tra trạng thái batch và thử lại.
      </Alert>
    );
  }

  return (
    <Box data-testid="batch-summary-results" aria-label="Kết quả summary theo từng loại">
      {showSources && job.source_manifest.length > 0 && (
        <Box component="ol" sx={{ mt: 0, mb: 2, pl: 3 }} data-testid="batch-summary-source-manifest">
          {job.source_manifest.map(source => (
            <Typography component="li" variant="body2" key={`${source.position}-${source.task_id}`}>
              {source.filename}
            </Typography>
          ))}
        </Box>
      )}
      {results.map((result, index) => {
        const label = BATCH_SUMMARY_TYPE_LABELS[result.summary_type];
        const ready = hasUsableBatchSummaryResult(result);
        const pending = result.status === 'queued' || result.status === 'processing' || result.status === 'cancel_requested';
        const partial = result.status === 'partially_succeeded';
        return (
          <Accordion
            key={result.summary_type}
            defaultExpanded={index === 0}
            data-testid={`batch-summary-result-${result.summary_type}`}
            sx={{ mb: 1.5, borderRadius: '8px !important', '&:before': { display: 'none' } }}
          >
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Box display="flex" alignItems="center" gap={1} width="100%" minWidth={0}>
                <Typography fontWeight={700} sx={{ overflowWrap: 'anywhere' }} flex={1}>
                  {label}
                </Typography>
                <Chip
                  size="small"
                  icon={ready ? <CheckCircleIcon /> : pending ? <CircularProgress size={14} /> : <ErrorOutlineIcon />}
                  color={ready ? (partial ? 'warning' : 'success') : pending ? 'warning' : 'error'}
                  label={ready ? (partial ? 'Hoàn tất một phần' : 'Hoàn tất') : pending ? 'Đang xử lý' : 'Chưa có kết quả'}
                />
              </Box>
            </AccordionSummary>
            <AccordionDetails>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
                {BATCH_SUMMARY_TYPE_DESCRIPTIONS[result.summary_type]}
              </Typography>
              {result.error && (
                <Alert severity="error" sx={{ mb: 1.5 }}>
                  {result.error.message || `Không thể tạo ${label} (${result.error.code}).`}
                </Alert>
              )}
              {ready ? (
                <>
                  <Box display="flex" justifyContent="flex-end" mb={1}>
                    <Button
                      size="small"
                      variant="outlined"
                      startIcon={<ContentCopyIcon />}
                      onClick={() => void copyResult(result.summary_type, result.summary)}
                      data-testid={`batch-summary-copy-${result.summary_type}`}
                    >
                      {copiedType === result.summary_type ? 'Đã copy' : 'Copy'}
                    </Button>
                  </Box>
                  <Typography sx={{ whiteSpace: 'pre-line', lineHeight: 1.8, overflowWrap: 'anywhere' }}>
                    {result.summary}
                  </Typography>
                </>
              ) : !result.error && !pending ? (
                <Typography color="text.secondary">Chưa có nội dung cho loại summary này.</Typography>
              ) : null}
            </AccordionDetails>
          </Accordion>
        );
      })}
    </Box>
  );
};

export default BatchSummaryResults;
