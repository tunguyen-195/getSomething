import React, { useMemo, useState } from 'react';
import { Alert, Box, Button, Chip, Paper, Typography } from '@mui/material';
import { CheckCircle as CheckCircleIcon, ContentCopy as ContentCopyIcon, ErrorOutline as ErrorOutlineIcon } from '@mui/icons-material';
import type { AudioBatchSummaryType } from '../api/client';
import { BATCH_SUMMARY_TYPE_DESCRIPTIONS, BATCH_SUMMARY_TYPE_LABELS, hasUsableBatchSummaryResult, normalizeBatchSummaryResults } from '../utils/batchSummary';

interface SummaryVariantsProps {
  summary?: string | null;
  summary_type?: AudioBatchSummaryType;
  summary_variants?: Record<string, unknown>;
}

/** Reader-safe per-file result surface. Each semantic output has its own slot. */
const SummaryVariants: React.FC<SummaryVariantsProps> = props => {
  const [copied, setCopied] = useState<string | null>(null);
  const results = useMemo(() => normalizeBatchSummaryResults(props as never), [props]);
  if (results.length === 0) return null;
  const copy = async (type: string, text: string) => {
    await navigator.clipboard?.writeText(text);
    setCopied(type);
    window.setTimeout(() => setCopied(value => value === type ? null : value), 1500);
  };
  return (
    <Box data-testid="file-summary-variants" display="flex" flexDirection="column" gap={1.5}>
      {results.map(result => {
        const ready = hasUsableBatchSummaryResult(result);
        const pending = result.status === 'queued' || result.status === 'processing' || result.status === 'cancel_requested';
        return (
          <Paper key={result.summary_type} variant="outlined" sx={{ p: 2 }} data-testid={`file-summary-${result.summary_type}`}>
            <Box display="flex" alignItems="center" gap={1} mb={1} flexWrap="wrap">
              <Typography fontWeight={700} flex={1}>{BATCH_SUMMARY_TYPE_LABELS[result.summary_type]}</Typography>
              <Chip size="small" icon={ready ? <CheckCircleIcon /> : <ErrorOutlineIcon />} color={ready ? 'success' : pending ? 'warning' : 'error'} label={ready ? 'Hoàn tất' : pending ? 'Đang xử lý' : 'Chưa có kết quả'} />
            </Box>
            <Typography variant="body2" color="text.secondary" mb={1}>{BATCH_SUMMARY_TYPE_DESCRIPTIONS[result.summary_type]}</Typography>
            {result.error && <Alert severity="error" sx={{ mb: 1 }}>{result.error.message || result.error.code}</Alert>}
            {ready && <>
              <Box display="flex" justifyContent="flex-end" mb={0.5}>
                <Button size="small" variant="outlined" startIcon={<ContentCopyIcon />} onClick={() => void copy(result.summary_type, result.summary)}>
                  {copied === result.summary_type ? 'Đã copy' : 'Copy'}
                </Button>
              </Box>
              <Typography sx={{ whiteSpace: 'pre-line', lineHeight: 1.8, overflowWrap: 'anywhere' }}>{result.summary}</Typography>
            </>}
          </Paper>
        );
      })}
    </Box>
  );
};

export default SummaryVariants;
