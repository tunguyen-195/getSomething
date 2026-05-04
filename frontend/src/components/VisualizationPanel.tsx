import React, { useEffect, useMemo, useState } from 'react';
import {
  Box,
  Typography,
  Paper,
  Chip,
  Divider,
  Card,
  CardContent,
  Grid,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  Tabs,
  Tab,
} from '@mui/material';
import {
  Timeline as TimelineIcon,
  Person as PersonIcon,
  Place as PlaceIcon,
  Event as EventIcon,
  Hub as HubIcon,
  AccessTime as TimeIcon,
} from '@mui/icons-material';
import { AnalysisGraphV2, LegacyVisualizationData, getLegacyVisualizationData } from '../utils/visualization';

interface VisualizationData extends LegacyVisualizationData {
  nodes?: Array<Record<string, any>>;
  edges?: Array<Record<string, any>>;
  timeline?: Array<Record<string, any>>;
  main_events?: string[];
  entity_types?: string[];
  legacy_view?: VisualizationData;
}

interface FileWithVisualization {
  task_id: string;
  filename: string;
  has_visualization?: boolean;
  visualization_data?: VisualizationData | AnalysisGraphV2 | null;
}

interface VisualizationPanelProps {
  files: FileWithVisualization[];
  focusTaskId?: string | null;
  showFileSelector?: boolean;
}

const VisualizationPanel: React.FC<VisualizationPanelProps> = ({ files, focusTaskId = null, showFileSelector = true }) => {
  const [activeTab, setActiveTab] = useState(0);
  const [selectedFile, setSelectedFile] = useState<string | null>(focusTaskId);

  const filesWithViz = useMemo(
    () => files.filter(f => f.has_visualization && f.visualization_data),
    [files],
  );

  useEffect(() => {
    if (focusTaskId && filesWithViz.some(f => f.task_id === focusTaskId)) {
      setSelectedFile(focusTaskId);
      return;
    }

    setSelectedFile(prev => {
      if (prev && filesWithViz.some(f => f.task_id === prev)) {
        return prev;
      }
      return filesWithViz[0]?.task_id || null;
    });
  }, [focusTaskId, filesWithViz]);

  // Get combined data from all files or selected file
  const getVisualizationData = (): VisualizationData => {
    const file = filesWithViz.find(f => f.task_id === selectedFile) || filesWithViz[0];
    if (file) {
      return getLegacyVisualizationData(file.visualization_data);
    }

    // Combine all visualization data
    const combined: VisualizationData = {
      nodes: [],
      edges: [],
      timeline: [],
      main_events: [],
      entity_types: [],
    };
    filesWithViz.forEach(f => {
      if (f.visualization_data) {
        const viz = getLegacyVisualizationData(f.visualization_data);
        combined.nodes = [...(combined.nodes || []), ...(viz.nodes || [])];
        combined.edges = [...(combined.edges || []), ...(viz.edges || [])];
        combined.timeline = [...(combined.timeline || []), ...(viz.timeline || [])];
        combined.main_events = [...(combined.main_events || []), ...(viz.main_events || [])];
      }
    });
    return combined;
  };

  const data = getVisualizationData();

  // Get entity type icon
  const getEntityIcon = (type?: string) => {
    switch (type?.toLowerCase()) {
      case 'person': return <PersonIcon sx={{ color: '#1976d2' }} />;
      case 'place':
      case 'location': return <PlaceIcon sx={{ color: '#43a047' }} />;
      case 'event': return <EventIcon sx={{ color: '#ff9800' }} />;
      default: return <HubIcon sx={{ color: '#9c27b0' }} />;
    }
  };

  // Get entity type color
  const getEntityColor = (type?: string) => {
    switch (type?.toLowerCase()) {
      case 'person': return '#1976d2';
      case 'place':
      case 'location': return '#43a047';
      case 'event': return '#ff9800';
      case 'time': return '#e91e63';
      default: return '#9c27b0';
    }
  };

  if (files.length === 0) {
    return (
      <Paper sx={{ p: 4, textAlign: 'center', borderRadius: '16px' }}>
        <TimelineIcon sx={{ fontSize: 64, color: '#bdbdbd', mb: 2 }} />
        <Typography variant="h6" color="text.secondary">
          No files uploaded yet
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Upload audio files and generate visualization to see results here
        </Typography>
      </Paper>
    );
  }

  if (filesWithViz.length === 0) {
    return (
      <Paper sx={{ p: 4, textAlign: 'center', borderRadius: '16px' }}>
        <TimelineIcon sx={{ fontSize: 64, color: '#9c27b0', mb: 2 }} />
        <Typography variant="h6" color="text.secondary">
          No visualization data available
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Click "Generate" button on transcribed files to create visualizations
        </Typography>
        <Chip
          label={`${files.filter(f => f.has_visualization === false).length} file(s) ready for visualization`}
          color="secondary"
        />
      </Paper>
    );
  }

  return (
    <Box>
      {/* Header */}
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Box display="flex" alignItems="center" gap={1}>
          <TimelineIcon sx={{ color: '#9c27b0', fontSize: 28 }} />
          <Typography variant="h6" fontWeight={700}>
            Visualization
          </Typography>
          <Chip
            label={`${filesWithViz.length} file(s)`}
            size="small"
            sx={{ ml: 1, bgcolor: '#9c27b0', color: '#fff' }}
          />
        </Box>
      </Box>

      {/* File selector (if multiple files) */}
      {showFileSelector && filesWithViz.length > 1 && (
        <Box mb={3}>
          <Typography variant="subtitle2" mb={1}>Select file:</Typography>
          <Box display="flex" flexWrap="wrap" gap={1}>
            {filesWithViz.map(f => (
              <Chip
                key={f.task_id}
                label={f.filename}
                variant={selectedFile === f.task_id ? "filled" : "outlined"}
                onClick={() => setSelectedFile(f.task_id)}
              />
            ))}
          </Box>
        </Box>
      )}

      {/* Visualization Tabs */}
      <Tabs
        value={activeTab}
        onChange={(_, v) => setActiveTab(v)}
        sx={{ mb: 3 }}
        variant="fullWidth"
      >
        <Tab icon={<TimelineIcon />} label="Timeline" />
        <Tab icon={<HubIcon />} label="Entities" />
        <Tab icon={<EventIcon />} label="Events" />
      </Tabs>

      {/* Tab Content */}
      {activeTab === 0 && (
        <Card sx={{ borderRadius: '16px', border: '2px solid rgba(156, 39, 176, 0.3)' }}>
          <CardContent>
            <Typography variant="h6" fontWeight={600} mb={2} display="flex" alignItems="center" gap={1}>
              <TimeIcon sx={{ color: '#9c27b0' }} /> Timeline
            </Typography>
            {data.timeline && data.timeline.length > 0 ? (
              <Box sx={{ position: 'relative', pl: 3 }}>
                {/* Timeline line */}
                <Box sx={{
                  position: 'absolute',
                  left: 10,
                  top: 0,
                  bottom: 0,
                  width: 3,
                  bgcolor: 'linear-gradient(180deg, #9c27b0, #673ab7)',
                  background: 'linear-gradient(180deg, #9c27b0, #673ab7)',
                  borderRadius: 2,
                }} />
                {data.timeline.map((item, idx) => (
                  <Box key={idx} sx={{ display: 'flex', mb: 2, position: 'relative' }}>
                    {/* Timeline dot */}
                    <Box sx={{
                      position: 'absolute',
                      left: -20,
                      width: 16,
                      height: 16,
                      borderRadius: '50%',
                      bgcolor: '#9c27b0',
                      border: '3px solid #fff',
                      boxShadow: '0 2px 8px rgba(156, 39, 176, 0.4)',
                    }} />
                    <Paper sx={{ p: 2, ml: 2, flex: 1, bgcolor: 'rgba(156, 39, 176, 0.05)' }}>
                      {item.time && (
                        <Chip label={item.time} size="small" sx={{ mb: 1, bgcolor: '#9c27b0', color: '#fff' }} />
                      )}
                      <Typography variant="body1">{item.event}</Typography>
                    </Paper>
                  </Box>
                ))}
              </Box>
            ) : (
              <Typography color="text.secondary">No timeline data available</Typography>
            )}
          </CardContent>
        </Card>
      )}

      {activeTab === 1 && (
        <Card sx={{ borderRadius: '16px', border: '2px solid rgba(156, 39, 176, 0.3)' }}>
          <CardContent>
            <Typography variant="h6" fontWeight={600} mb={2} display="flex" alignItems="center" gap={1}>
              <HubIcon sx={{ color: '#9c27b0' }} /> Entities
            </Typography>
            {data.nodes && data.nodes.length > 0 ? (
              <Grid container spacing={2}>
                {data.nodes.map((node, idx) => (
                  <Grid item xs={12} sm={6} md={4} key={idx}>
                    <Paper
                      sx={{
                        p: 2,
                        display: 'flex',
                        alignItems: 'center',
                        gap: 1.5,
                        bgcolor: 'rgba(156, 39, 176, 0.05)',
                        border: `2px solid ${getEntityColor(node.type)}30`,
                        borderRadius: '12px',
                        transition: 'all 0.2s',
                        '&:hover': {
                          transform: 'translateY(-2px)',
                          boxShadow: `0 4px 12px ${getEntityColor(node.type)}40`,
                        },
                      }}
                    >
                      {getEntityIcon(node.type)}
                      <Box>
                        <Typography fontWeight={600}>{node.label}</Typography>
                        {node.type && (
                          <Chip
                            label={node.type}
                            size="small"
                            sx={{
                              bgcolor: `${getEntityColor(node.type)}20`,
                              color: getEntityColor(node.type),
                              fontWeight: 600,
                              mt: 0.5,
                            }}
                          />
                        )}
                      </Box>
                    </Paper>
                  </Grid>
                ))}
              </Grid>
            ) : (
              <Typography color="text.secondary">No entities found</Typography>
            )}

            {/* Relationships */}
            {data.edges && data.edges.length > 0 && (
              <>
                <Divider sx={{ my: 3 }} />
                <Typography variant="subtitle1" fontWeight={600} mb={2}>
                  Relationships ({data.edges.length})
                </Typography>
                <List dense>
                  {data.edges.slice(0, 10).map((edge, idx) => (
                    <ListItem key={idx}>
                      <ListItemIcon><HubIcon color="action" /></ListItemIcon>
                      <ListItemText
                        primary={`${edge.from} → ${edge.to}`}
                        secondary={edge.label}
                      />
                    </ListItem>
                  ))}
                  {data.edges.length > 10 && (
                    <Typography variant="caption" color="text.secondary" sx={{ ml: 2 }}>
                      +{data.edges.length - 10} more relationships
                    </Typography>
                  )}
                </List>
              </>
            )}
          </CardContent>
        </Card>
      )}

      {activeTab === 2 && (
        <Card sx={{ borderRadius: '16px', border: '2px solid rgba(156, 39, 176, 0.3)' }}>
          <CardContent>
            <Typography variant="h6" fontWeight={600} mb={2} display="flex" alignItems="center" gap={1}>
              <EventIcon sx={{ color: '#9c27b0' }} /> Main Events
            </Typography>
            {data.main_events && data.main_events.length > 0 ? (
              <List>
                {data.main_events.map((event, idx) => (
                  <ListItem key={idx} sx={{
                    bgcolor: 'rgba(156, 39, 176, 0.05)',
                    borderRadius: '8px',
                    mb: 1,
                  }}>
                    <ListItemIcon>
                      <Chip label={idx + 1} size="small" sx={{ bgcolor: '#9c27b0', color: '#fff', fontWeight: 700 }} />
                    </ListItemIcon>
                    <ListItemText primary={event} />
                  </ListItem>
                ))}
              </List>
            ) : (
              <Typography color="text.secondary">No main events identified</Typography>
            )}
          </CardContent>
        </Card>
      )}
    </Box>
  );
};

export default VisualizationPanel;
