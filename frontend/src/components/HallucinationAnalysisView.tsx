import React from 'react';
import {
  Alert,
  Box,
  Chip,
  Divider,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import { HallucinationAnalysis, HallucinationSpan } from '../utils/visualization';

interface HallucinationAnalysisViewProps {
  analysis?: HallucinationAnalysis | null;
}

const statusColor = (status?: string): 'default' | 'success' | 'warning' | 'error' | 'info' => {
  switch (status) {
    case 'filtered':
      return 'error';
    case 'flagged':
      return 'warning';
    case 'kept_for_review':
      return 'info';
    default:
      return 'default';
  }
};

const statusLabel = (status?: string): string => {
  switch (status) {
    case 'filtered':
      return 'Đã lọc';
    case 'flagged':
      return 'Nghi ảo giác';
    case 'kept_for_review':
      return 'Cần review';
    default:
      return status || 'Unknown';
  }
};

const formatTime = (value?: number | null): string => {
  if (typeof value !== 'number') return 'n/a';
  return `${value.toFixed(2)}s`;
};

const formatSpanTime = (span: HallucinationSpan): string => {
  const start = formatTime(span.start_time ?? null);
  const end = formatTime(span.end_time ?? null);
  if (start === 'n/a' && end === 'n/a') return 'n/a';
  if (start !== 'n/a' && end !== 'n/a') return `${start} - ${end}`;
  return start !== 'n/a' ? start : end;
};

const renderHighlightedTranscript = (text: string, spans: HallucinationSpan[]) => {
  if (!text) {
    return <Typography color="text.secondary">Không có transcript để hiển thị.</Typography>;
  }
  const usable = spans
    .filter(span => typeof span.char_start === 'number' && typeof span.char_end === 'number' && (span.char_end || 0) > (span.char_start || 0))
    .sort((a, b) => (a.char_start || 0) - (b.char_start || 0) || (a.char_end || 0) - (b.char_end || 0));

  if (usable.length === 0) {
    return <Typography sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{text}</Typography>;
  }

  const nodes: React.ReactNode[] = [];
  let cursor = 0;

  usable.forEach((span, index) => {
    const start = Math.max(0, span.char_start || 0);
    const end = Math.min(text.length, span.char_end || 0);
    if (end <= cursor) {
      return;
    }
    if (start > cursor) {
      nodes.push(
        <Box component="span" key={`text-${index}-${cursor}`} sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
          {text.slice(cursor, start)}
        </Box>,
      );
    }
    const slice = text.slice(start, end);
    const background = span.status === 'filtered'
      ? 'rgba(244, 67, 54, 0.16)'
      : span.status === 'kept_for_review'
        ? 'rgba(33, 150, 243, 0.15)'
        : 'rgba(255, 193, 7, 0.22)';
    const decoration = span.status === 'filtered' ? 'line-through' : 'none';
    const tooltip = [
      statusLabel(span.status),
      span.reason_vi,
      span.llm_review?.verdict ? `LLM: ${span.llm_review.verdict}` : '',
    ].filter(Boolean).join(' | ');
    nodes.push(
      <Box
        component="span"
        key={span.id || `span-${index}`}
        title={tooltip}
        sx={{
          whiteSpace: 'pre-wrap',
          overflowWrap: 'anywhere',
          px: 0.35,
          borderRadius: 0.5,
          background,
          textDecoration: decoration,
          textDecorationColor: 'currentColor',
          cursor: 'help',
        }}
      >
        {slice}
      </Box>,
    );
    cursor = end;
  });

  if (cursor < text.length) {
    nodes.push(
      <Box component="span" key={`tail-${cursor}`} sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
        {text.slice(cursor)}
      </Box>,
    );
  }

  return (
    <Typography component="div" sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', lineHeight: 1.8 }}>
      {nodes}
    </Typography>
  );
};

const HallucinationAnalysisView: React.FC<HallucinationAnalysisViewProps> = ({ analysis }) => {
  if (!analysis) {
    return (
      <Alert severity="info">
        Chưa có `hallucination_analysis` từ backend.
      </Alert>
    );
  }

  const spans = Array.isArray(analysis.spans) ? analysis.spans : [];
  const rawTranscript = analysis.raw_transcript || '';
  const filteredTranscript = analysis.filtered_transcript || '';

  return (
    <Box>
      <Paper sx={{ p: 2, mb: 2, borderRadius: 2, border: '1px solid rgba(244, 67, 54, 0.15)' }}>
        <Box display="flex" alignItems="center" gap={1} mb={1}>
          <WarningAmberIcon color="warning" />
          <Typography variant="subtitle1" fontWeight={700}>
            Lọc ảo giác / sai ngữ cảnh
          </Typography>
        </Box>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          Phần này hiển thị rõ đoạn nào đã bị lọc, đoạn nào còn nghi ảo giác, và transcript sau khi guard đã xử lý.
        </Typography>
        {analysis.summary_vi && (
          <Alert severity={analysis.review_required ? 'warning' : 'success'} sx={{ mb: 1.5 }}>
            {analysis.summary_vi}
          </Alert>
        )}
        <Box display="flex" flexWrap="wrap" gap={1}>
          <Chip label={`Đã lọc ${analysis.removed_count || 0}`} color="error" size="small" />
          <Chip label={`Nghi ngờ ${analysis.flagged_count || 0}`} color="warning" size="small" />
          <Chip label={analysis.review_required ? 'Cần rà soát' : 'Không cần rà soát'} color={analysis.review_required ? 'warning' : 'success'} size="small" />
          <Chip label={`LLM: ${analysis.llm_status || 'disabled'}`} size="small" variant="outlined" />
        </Box>
      </Paper>

      <Paper sx={{ p: 2, mb: 2, borderRadius: 2, border: '1px solid rgba(33, 150, 243, 0.15)' }}>
        <Typography variant="subtitle2" fontWeight={700} mb={1}>
          Cơ sở nghiên cứu
        </Typography>
        <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
          {(analysis.research_basis_vi || []).map((item, idx) => (
            <li key={idx}>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
                {item}
              </Typography>
            </li>
          ))}
        </Box>
      </Paper>

      <Box mb={2}>
        <Typography variant="subtitle2" fontWeight={700} mb={1}>
          Transcript gốc
        </Typography>
        <Paper variant="outlined" sx={{ p: 2, bgcolor: 'rgba(244, 67, 54, 0.03)' }}>
          {renderHighlightedTranscript(rawTranscript, spans)}
        </Paper>
      </Box>

      <Box mb={2}>
        <Typography variant="subtitle2" fontWeight={700} mb={1}>
          Transcript sau lọc
        </Typography>
        <Paper variant="outlined" sx={{ p: 2, bgcolor: 'rgba(76, 175, 80, 0.04)' }}>
          <Typography sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', lineHeight: 1.8 }}>
            {filteredTranscript || 'Không có transcript sau lọc.'}
          </Typography>
        </Paper>
      </Box>

      <Divider sx={{ my: 2 }} />

      {spans.length === 0 ? (
        <Alert severity="success">
          Chưa có span nghi ảo giác rõ ràng trong transcript này.
        </Alert>
      ) : (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Trạng thái</TableCell>
                <TableCell>Đoạn nghi ngờ</TableCell>
                <TableCell>Đã lọc</TableCell>
                <TableCell>Lý do</TableCell>
                <TableCell>Thời gian</TableCell>
                <TableCell>LLM</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {spans.map(span => (
                <TableRow key={span.id}>
                  <TableCell>
                    <Chip label={statusLabel(span.status)} color={statusColor(span.status)} size="small" />
                  </TableCell>
                  <TableCell sx={{ maxWidth: 280, wordBreak: 'break-word', whiteSpace: 'pre-wrap' }}>
                    {span.text}
                  </TableCell>
                  <TableCell sx={{ maxWidth: 280, wordBreak: 'break-word', whiteSpace: 'pre-wrap' }}>
                    {span.filtered_text || '-'}
                  </TableCell>
                  <TableCell sx={{ maxWidth: 260, wordBreak: 'break-word', whiteSpace: 'pre-wrap' }}>
                    {span.reason_vi}
                  </TableCell>
                  <TableCell>{formatSpanTime(span)}</TableCell>
                  <TableCell sx={{ maxWidth: 240, wordBreak: 'break-word', whiteSpace: 'pre-wrap' }}>
                    {span.llm_review ? (
                      <Box>
                        <Typography variant="body2" fontWeight={600}>
                          {span.llm_review.verdict || 'unknown'}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          {span.llm_review.reason_vi || ''}
                        </Typography>
                      </Box>
                    ) : (
                      '-'
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <Box mt={2}>
        <Typography variant="caption" color="text.secondary">
          Các span này chỉ là gợi ý lọc ảo giác. Nếu transcript rất ngắn hoặc nói ngắt quãng, nên mở raw transcript và nghe lại audio gốc.
        </Typography>
      </Box>
    </Box>
  );
};

export default HallucinationAnalysisView;
