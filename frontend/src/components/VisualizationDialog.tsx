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
  Divider,
  List,
  ListItem,
  ListItemText,
  Typography,
} from '@mui/material';
import { Timeline, TimelineConnector, TimelineContent, TimelineDot, TimelineItem, TimelineSeparator } from '@mui/lab';
import CloseIcon from '@mui/icons-material/Close';
import InsightsIcon from '@mui/icons-material/Insights';
import ReactFlow, { Background, Controls, MiniMap } from 'react-flow-renderer';
import { apiFetch } from '../api/client';
import {
  ReleasedVisualizationArtifact,
  selectReleasedVisualizationArtifactFromTask,
} from '../utils/investigationProjection';

interface VisualizationDialogProps {
  open: boolean;
  onClose: () => void;
  taskId: string | null;
}

const API_BASE_URL = typeof window !== 'undefined' && (window as any).API_BASE_URL
  ? (window as any).API_BASE_URL
  : '';

const VisualizationDialog: React.FC<VisualizationDialogProps> = ({ open, onClose, taskId }) => {
  const [loading, setLoading] = useState(false);
  const [artifact, setArtifact] = useState<ReleasedVisualizationArtifact | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!open || !taskId) {
      setLoading(false);
      setArtifact(null);
      setError(null);
      return () => { cancelled = true; };
    }

    setLoading(true);
    setArtifact(null);
    setError(null);

    apiFetch(`${API_BASE_URL}/api/v1/audio/tasks/${taskId}`)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((taskData) => {
        if (cancelled) return;
        const validation = selectReleasedVisualizationArtifactFromTask(taskData);
        if (!validation.ok) {
          setError(`Released visualization rejected: ${validation.error}`);
          return;
        }
        setArtifact(validation.value);
      })
      .catch((requestError) => {
        if (cancelled) return;
        console.error('Failed to load released visualization:', requestError);
        setError('Failed to load released visualization artifact.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [open, taskId]);

  const graph = useMemo(() => {
    if (!artifact) return { nodes: [], edges: [] };
    const columns = Math.max(1, Math.ceil(Math.sqrt(artifact.nodes.length)));
    return {
      nodes: artifact.nodes.map((node, index) => ({
        id: node.id,
        data: { label: `${node.label} (${node.type})` },
        position: {
          x: (index % columns) * 220,
          y: Math.floor(index / columns) * 120,
        },
      })),
      edges: artifact.edges.map((edge, index) => ({
        id: edge.id || `released-edge-${index}-${edge.source}-${edge.target}`,
        source: edge.source,
        target: edge.target,
        label: edge.label,
      })),
    };
  }, [artifact]);

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="lg"
      fullWidth
      PaperProps={{
        sx: {
          borderRadius: '16px',
          border: '2px solid #9c27b0',
          boxShadow: '0 8px 32px rgba(156, 39, 176, 0.2)',
        },
      }}
    >
      <DialogTitle
        sx={{
          bgcolor: '#9c27b0',
          color: '#fff',
          fontWeight: 800,
          display: 'flex',
          alignItems: 'center',
          gap: 1,
        }}
      >
        <InsightsIcon />
        Released investigation visualization
      </DialogTitle>

      <DialogContent sx={{ mt: 2 }}>
        {loading ? (
          <Box display="flex" flexDirection="column" alignItems="center" justifyContent="center" minHeight={240} gap={2}>
            <CircularProgress size={48} sx={{ color: '#9c27b0' }} />
            <Typography color="text.secondary">Loading released artifact...</Typography>
          </Box>
        ) : error ? (
          <Alert severity="warning">{error}</Alert>
        ) : artifact ? (
          <Box>
            <Alert severity="success" sx={{ mb: 2 }}>
              Validated authority: <b>{artifact.authority}</b>
            </Alert>
            <Box display="flex" gap={1} flexWrap="wrap" mb={2}>
              <Chip label={`Run: ${artifact.run_id}`} size="small" />
              <Chip label={`Source: ${artifact.source_revision_id}`} size="small" />
              <Chip label={`SHA-256: ${artifact.content_hash.slice(0, 12)}...`} size="small" />
            </Box>

            <Typography variant="h6" fontWeight={700} mb={1}>Relationship graph</Typography>
            {graph.nodes.length > 0 ? (
              <Box sx={{ height: 360, bgcolor: '#f7f9fc', borderRadius: 2, border: '1px solid #dfe5ec' }}>
                <ReactFlow nodes={graph.nodes} edges={graph.edges} fitView>
                  <MiniMap />
                  <Controls />
                  <Background />
                </ReactFlow>
              </Box>
            ) : (
              <Alert severity="info">The released artifact contains no relationship nodes.</Alert>
            )}

            <Divider sx={{ my: 3 }} />
            <Typography variant="h6" fontWeight={700}>Main events</Typography>
            {artifact.main_events.length > 0 ? (
              <List dense>
                {artifact.main_events.map((item, index) => (
                  <ListItem key={item.id || `${item.event}-${index}`}>
                    <ListItemText primary={item.event} secondary={item.type} />
                  </ListItem>
                ))}
              </List>
            ) : (
              <Typography color="text.secondary">No released main events.</Typography>
            )}

            <Typography variant="h6" fontWeight={700} mt={2}>Timeline</Typography>
            {artifact.timeline.length > 0 ? (
              <Timeline position="right">
                {artifact.timeline.map((item, index) => (
                  <TimelineItem key={item.id || `${item.event}-${index}`}>
                    <TimelineSeparator>
                      <TimelineDot color="secondary" />
                      {index < artifact.timeline.length - 1 && <TimelineConnector />}
                    </TimelineSeparator>
                    <TimelineContent>
                      <Typography fontWeight={700}>{item.time || `Event ${index + 1}`}</Typography>
                      <Typography>{item.event}</Typography>
                    </TimelineContent>
                  </TimelineItem>
                ))}
              </Timeline>
            ) : (
              <Typography color="text.secondary">No released timeline events.</Typography>
            )}

            <Typography variant="h6" fontWeight={700} mt={2}>Extracted entities</Typography>
            {artifact.extracted_entities.length > 0 ? (
              <Box display="flex" gap={1} flexWrap="wrap" mt={1}>
                {artifact.extracted_entities.map((entity, index) => (
                  <Chip
                    key={`${entity.type}-${entity.value}-${index}`}
                    label={`${entity.value} (${entity.type})`}
                    title={entity.context || undefined}
                    variant="outlined"
                  />
                ))}
              </Box>
            ) : (
              <Typography color="text.secondary">No released entities.</Typography>
            )}
          </Box>
        ) : null}
      </DialogContent>

      <DialogActions sx={{ p: 2 }}>
        <Button
          onClick={onClose}
          variant="contained"
          startIcon={<CloseIcon />}
          sx={{
            bgcolor: '#9c27b0',
            textTransform: 'none',
            fontWeight: 700,
            '&:hover': { bgcolor: '#7b1fa2' },
          }}
        >
          Close
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export default VisualizationDialog;
