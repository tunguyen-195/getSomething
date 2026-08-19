import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  LinearProgress,
  List,
  ListItem,
  ListItemText,
  Paper,
  Typography,
} from '@mui/material';
import {
  Timeline,
  TimelineConnector,
  TimelineContent,
  TimelineDot,
  TimelineItem,
  TimelineSeparator,
} from '@mui/lab';
import CloseIcon from '@mui/icons-material/Close';
import InsightsIcon from '@mui/icons-material/Insights';
import ReactFlow, { Background, Controls, MiniMap } from 'react-flow-renderer';
import { apiFetch } from '../api/client';
import {
  analysisContextFromTask,
  buildInvestigationVisualization,
  projectInvestigationAnalysis,
} from '../utils/investigationAnalysis';

interface VisualizationDialogProps {
  open: boolean;
  onClose: () => void;
  taskId: string | null;
}

const API_BASE_URL = typeof window !== 'undefined' && (window as any).API_BASE_URL
  ? (window as any).API_BASE_URL
  : '';

const STATUS_LABELS: Record<string, string> = {
  planned: 'Dự kiến',
  reported: 'Được nhắc tới',
  completed: 'Đã hoàn thành',
  open: 'Cần làm tiếp',
  pending: 'Đang chờ',
  uncertain: 'Chưa rõ',
};

const VisualizationDialog: React.FC<VisualizationDialogProps> = ({ open, onClose, taskId }) => {
  const [loading, setLoading] = useState(false);
  const [taskData, setTaskData] = useState<unknown>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!open || !taskId) {
      setLoading(false);
      setTaskData(null);
      setError(null);
      return () => { cancelled = true; };
    }

    setLoading(true);
    setTaskData(null);
    setError(null);
    // Visualization is a read-only projection of persisted Analysis; changing views never starts generation.
    apiFetch(`${API_BASE_URL}/api/v1/audio/tasks/${taskId}`)
      .then(response => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then(payload => {
        if (!cancelled) setTaskData(payload);
      })
      .catch(requestError => {
        if (cancelled) return;
        console.error('Failed to load Analysis visualization:', requestError);
        setError('Không thể tải dữ liệu Analysis của file này.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [open, taskId]);

  const preview = useMemo(
    () => taskData ? buildInvestigationVisualization(taskData) : null,
    [taskData],
  );
  const analysis = useMemo(() => {
    if (!taskData) return null;
    return projectInvestigationAnalysis(analysisContextFromTask(taskData) ?? taskData);
  }, [taskData]);
  const graph = useMemo(() => {
    const sourceNodes = preview?.nodes ?? [];
    const columns = Math.max(1, Math.ceil(Math.sqrt(sourceNodes.length)));
    return {
      nodes: sourceNodes.map((node, index) => ({
        id: node.id,
        data: { label: `${node.label} (${node.type})` },
        position: {
          x: (index % columns) * 230,
          y: Math.floor(index / columns) * 125,
        },
      })),
      edges: (preview?.edges ?? []).map((edge, index) => ({
        id: edge.id || `edge-${index}`,
        source: edge.source,
        target: edge.target,
        label: edge.label,
      })),
    };
  }, [preview]);
  const hasStructuredVisualizationData = Boolean(preview && (
    preview.timeline.length
    || preview.nodes.length
    || preview.edges.length
    || preview.entity_frequencies.length
    || preview.action_statuses.length
  ));
  const isTextOnlyAnalysis = Boolean(analysis?.analysis_text && !hasStructuredVisualizationData);
  const hasVisualization = Boolean(preview && (
    hasStructuredVisualizationData
    || preview.speaker_contributions.length
  ));

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="lg"
      fullWidth
      PaperProps={{ sx: { borderRadius: 3, overflow: 'hidden' } }}
    >
      <DialogTitle sx={{ bgcolor: '#0b5f69', color: '#fff', fontWeight: 800, display: 'flex', gap: 1 }}>
        <InsightsIcon />
        Trực quan hóa Analysis
      </DialogTitle>
      <DialogContent sx={{ mt: 2 }}>
        {loading ? (
          <Box display="flex" flexDirection="column" alignItems="center" justifyContent="center" minHeight={260} gap={2}>
            <CircularProgress sx={{ color: '#0b5f69' }} />
            <Typography color="text.secondary">Đang tải dữ liệu đã phân tích...</Typography>
          </Box>
        ) : error ? (
          <Alert severity="warning">{error}</Alert>
        ) : isTextOnlyAnalysis ? (
          <Alert severity="info">
            Analysis dạng văn bản đã có, nhưng chưa có dữ liệu cấu trúc để dựng timeline hoặc sơ đồ quan hệ.
            Vui lòng xem nội dung đầy đủ tại tab Analysis.
          </Alert>
        ) : !hasVisualization ? (
          <Alert severity="info">
            Analysis hiện chưa có sự kiện, quan hệ, thực thể, công việc hoặc dữ liệu người nói để trực quan hóa.
          </Alert>
        ) : preview ? (
          <Box>
            <Alert severity="info" sx={{ mb: 2 }}>
              Biểu đồ được dựng trực tiếp từ Analysis và các đoạn hội thoại đã lưu, không gọi LLM thêm khi đổi cách xem.
            </Alert>

            {preview.speaker_contributions.length > 0 && (
              <Box mb={3}>
                <Typography variant="h6" fontWeight={800} mb={1}>Mức độ tham gia của người nói</Typography>
                <GridLikeCards>
                  {preview.speaker_contributions.map(item => (
                    <Paper key={item.speaker} variant="outlined" sx={{ p: 1.5, minWidth: 220, flex: '1 1 220px' }}>
                      <Box display="flex" justifyContent="space-between" gap={1} mb={0.75}>
                        <Typography fontWeight={700}>{item.speaker}</Typography>
                        <Typography fontWeight={800} color="primary">{item.percentage}%</Typography>
                      </Box>
                      <LinearProgress variant="determinate" value={item.percentage} sx={{ height: 8, borderRadius: 8 }} />
                      <Typography variant="caption" color="text.secondary">
                        {item.word_count} từ trong {item.segment_count} đoạn
                      </Typography>
                    </Paper>
                  ))}
                </GridLikeCards>
              </Box>
            )}

            {preview.timeline.length > 0 && (
              <Box mb={3}>
                <Typography variant="h6" fontWeight={800}>Timeline sự kiện</Typography>
                <Timeline position="right" sx={{ px: 0 }}>
                  {preview.timeline.map((item, index) => (
                    <TimelineItem key={item.id}>
                      <TimelineSeparator>
                        <TimelineDot sx={{ bgcolor: '#0b5f69' }} />
                        {index < preview.timeline.length - 1 && <TimelineConnector />}
                      </TimelineSeparator>
                      <TimelineContent>
                        <Typography fontWeight={700}>{item.time || 'Không nêu thời gian'}</Typography>
                        <Typography>{item.event}</Typography>
                      </TimelineContent>
                    </TimelineItem>
                  ))}
                </Timeline>
              </Box>
            )}

            {(preview.nodes.length > 0 || preview.edges.length > 0) && (
              <Box mb={3}>
                <Typography variant="h6" fontWeight={800} mb={1}>Sơ đồ đối tượng và quan hệ</Typography>
                <Box sx={{ height: { xs: 360, md: 430 }, bgcolor: '#f4f8f8', borderRadius: 2, border: '1px solid #cddddd' }}>
                  <ReactFlow nodes={graph.nodes} edges={graph.edges} fitView>
                    <MiniMap />
                    <Controls />
                    <Background />
                  </ReactFlow>
                </Box>
              </Box>
            )}

            {preview.entity_frequencies.length > 0 && (
              <Box mb={3}>
                <Typography variant="h6" fontWeight={800} mb={1}>Thực thể được nhắc tới</Typography>
                <GridLikeCards>
                  {preview.entity_frequencies.map(item => (
                    <Paper key={`${item.type}-${item.label}`} variant="outlined" sx={{ p: 1.25, minWidth: 180, flex: '1 1 180px' }}>
                      <Typography fontWeight={800}>{item.label}</Typography>
                      <Box display="flex" gap={0.75} mt={0.75} flexWrap="wrap">
                        <Chip size="small" label={item.type} variant="outlined" />
                        <Chip size="small" label={`${item.count} lượt`} color="info" />
                      </Box>
                    </Paper>
                  ))}
                </GridLikeCards>
              </Box>
            )}

            {preview.action_statuses.length > 0 && (
              <Box>
                <Typography variant="h6" fontWeight={800}>Tổng quan hành động và trạng thái</Typography>
                <List dense disablePadding>
                  {preview.action_statuses.map(item => (
                    <ListItem key={item.status} divider>
                      <ListItemText primary={STATUS_LABELS[item.status] || item.status} />
                      <Chip label={item.count} size="small" />
                    </ListItem>
                  ))}
                </List>
              </Box>
            )}
          </Box>
        ) : null}
      </DialogContent>
      <DialogActions sx={{ p: 2 }}>
        <Button
          onClick={onClose}
          variant="contained"
          startIcon={<CloseIcon />}
          sx={{ bgcolor: '#0b5f69', textTransform: 'none', '&:hover': { bgcolor: '#084950' } }}
        >
          Đóng
        </Button>
      </DialogActions>
    </Dialog>
  );
};

function GridLikeCards({ children }: { children: React.ReactNode }) {
  return <Box display="flex" gap={1} flexWrap="wrap">{children}</Box>;
}

export default VisualizationDialog;
