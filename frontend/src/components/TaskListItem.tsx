import React from 'react';
import {
  ListItem,
  Grid,
  Checkbox,
  Avatar,
  Typography,
  Chip,
  Card,
  Box,
  Tooltip,
  IconButton,
  Collapse,
  Divider,
  LinearProgress,
  Button,
  Paper,
  CircularProgress,
  Tabs,
  Tab,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import DownloadIcon from '@mui/icons-material/Download';
import AccessTimeIcon from '@mui/icons-material/AccessTime';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import SummarizeIcon from '@mui/icons-material/Summarize';
import AudiotrackIcon from '@mui/icons-material/Audiotrack';
import dayjs from 'dayjs';
import InvestigationSummaryCard from './InvestigationSummaryCard';
import AudioPlayer from 'react-h5-audio-player';
import 'react-h5-audio-player/lib/styles.css';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import { useState } from 'react';

interface Task {
  id: string;
  status: string;
  filename: string;
  result?: any;
  created_at?: string;
  updated_at?: string;
  summary?: string;
  transcript?: string;
  case_id?: string;
  type?: string;
  case?: { title: string };
  files?: { filename: string }[];
  content?: string;
}

interface TaskListItemProps {
  task: Task;
  isSelected: boolean;
  onSelect: (taskId: string) => void;
  isExpanded: boolean;
  onToggleExpand: (taskId: string) => void;
  onDownload: (task: Task) => void;
  onEditContext: (task: Task) => void;
  isEditingContext: boolean;
  isResummarizing: boolean;
  // Prop để pass trạng thái expand/collapse summary từ TaskList
  expandedSummaryId: string | null;
  onToggleExpandSummary: (taskId: string | null) => void;
}

// Helper functions (có thể move ra ngoài nếu dùng chung)
const getStatusColor = (status: string) => {
  switch (status) {
    case 'completed':
      return 'success';
    case 'processing':
      return 'primary';
    case 'failed':
      return 'error';
    default:
      return 'default';
  }
};

const getStatusIcon = (status: string) => {
  switch (status) {
    case 'completed':
      return <CheckCircleIcon color="success" />;
    case 'processing':
      return <CircularProgress size={20} color="primary" />;
    case 'failed':
      return <ErrorIcon color="error" />;
    default:
      return <AccessTimeIcon color="disabled" />;
  }
};

const TaskListItem: React.FC<TaskListItemProps> = ({
  task,
  isSelected,
  onSelect,
  isExpanded,
  onToggleExpand,
  onDownload,
  onEditContext,
  isEditingContext,
  isResummarizing,
  expandedSummaryId,
  onToggleExpandSummary,
}) => {
  const transcript = task.result?.transcription || task.result?.text || task.transcript || '';
  const summary = task.result?.summary || task.summary || '';
  const [tab, setTab] = React.useState(
    (task.result?.summary || task.result?.context_analysis) ? 0 : 1
  );
  const [copiedTranscript, setCopiedTranscript] = useState(false);
  const [copiedSummary, setCopiedSummary] = useState(false);

  return (
    <Paper
      elevation={isExpanded ? 8 : 2}
      sx={{
        mb: 2,
        borderRadius: 3,
        transition: 'box-shadow 0.3s',
        ':hover': { boxShadow: 6 },
        background: isExpanded
          ? '#e3f0ff' // Nhẹ hơn màu của TaskList
          : '#f8fafc',
      }}
    >
      <ListItem alignItems="flex-start" divider sx={{ p: 2 }}>
        <Grid container alignItems="center" spacing={2}>
          <Grid item>
            <Checkbox
              checked={isSelected}
              onChange={() => onSelect(task.id)}
              disabled={task.status !== 'completed'}
              sx={{ p: 0 }}
            />
          </Grid>
          <Grid item>
            <Avatar sx={{ bgcolor: '#1976d2', width: 48, height: 48 }}>
              <AudiotrackIcon />
            </Avatar>
          </Grid>
          <Grid item xs={12} sm={3} md={2} lg={2}>
            <Typography fontWeight={600}>{task.filename}</Typography>
            <Typography variant="caption" color="text.secondary">
              {task.created_at ? dayjs(task.created_at).format('HH:mm DD/MM/YYYY') : ''}
            </Typography>
          </Grid>
          <Grid item xs={12} sm={2} md={2} lg={2}>
            <Chip
              label={task.status === 'completed' ? 'Hoàn thành' : task.status === 'processing' ? 'Đang xử lý' : 'Lỗi'}
              color={getStatusColor(task.status)}
              icon={getStatusIcon(task.status)}
              sx={{ fontWeight: 600, fontSize: 14 }}
            />
          </Grid>
          <Grid item xs={12} sm={3} md={3} lg={3}>
            <Typography variant="body2" color="primary" fontWeight={500}>Tóm tắt:</Typography>
             <Typography variant="body2" color="text.secondary" sx={{ whiteSpace: 'pre-wrap', maxHeight: 60, overflow: 'hidden', textOverflow: 'ellipsis' }}>{summary || 'Không có tóm tắt'}</Typography>
          </Grid>
          <Grid item xs={12} sm={2} md={2} lg={2}>
            <Tooltip title="Xem chi tiết">
              <IconButton onClick={() => onToggleExpand(task.id)} size="large" sx={{ color: '#1976d2' }}>
                {isExpanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
              </IconButton>
            </Tooltip>
            <Tooltip title="Tải kết quả">
              <span>
                <IconButton onClick={() => onDownload(task)} disabled={!task.result} size="large" sx={{ color: '#1976d2' }}>
                  <DownloadIcon />
                </IconButton>
              </span>
            </Tooltip>
          </Grid>
        </Grid>
      </ListItem>
      <Collapse in={isExpanded} sx={{ width: '100%' }}>
        <Divider />
        <Box sx={{ p: 3, background: '#f4f7fa', borderRadius: 2 }}>
          <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
            <Tab label="Data Visualization" />
            <Tab label="Details" />
          </Tabs>
          {tab === 0 && (
            <InvestigationSummaryCard summary={task.result?.summary} contextAnalysis={task.result?.context_analysis} taskId={task.result?.task_id || task.id} />
          )}
          {tab === 1 && (
            <Grid container spacing={2}>
               {/* Phần tóm tắt chi tiết - Luôn hiển thị đầy đủ nội dung */} 
               <Grid item xs={12} md={6}>
                 <Card sx={{ bgcolor: '#f8f9fa', borderRadius: 4, boxShadow: 3, p: 3, minHeight: 100, mb: 1, position: 'relative', display: 'flex', flexDirection: 'column', justifyContent: 'flex-start' }}>
                   <Box display="flex" alignItems="center" mb={1}>
                     <Typography variant="h6" color="primary" fontWeight={700} sx={{ display: 'flex', alignItems: 'center', fontSize: 18 }}>
                       <SummarizeIcon sx={{ mr: 1, color: '#1976d2' }} />Tóm tắt chi tiết
                     </Typography>
                     <Tooltip title={copiedSummary ? 'Đã copy!' : 'Copy summary'}>
                       <Button size="small" variant="outlined" color={copiedSummary ? 'success' : 'primary'} sx={{ ml: 2 }} startIcon={<ContentCopyIcon />} onClick={() => {navigator.clipboard.writeText(summary); setCopiedSummary(true); setTimeout(() => setCopiedSummary(false), 1500);}}>{copiedSummary ? 'Đã copy' : 'Copy'}</Button>
                     </Tooltip>
                   </Box>
                   <Typography
                     variant="body1"
                     color="text.primary"
                     sx={{ whiteSpace: 'pre-wrap', fontWeight: 500, fontSize: 16 }}
                   >
                     {summary || 'Không có tóm tắt'}
                   </Typography>
                 </Card>
               </Grid>
              <Grid item xs={12} md={6}>
                <Box display="flex" alignItems="center" mb={1}>
                  <Typography variant="subtitle2" fontWeight={700} fontSize={16} mr={2}>Transcript</Typography>
                  <Tooltip title={copiedTranscript ? 'Đã copy!' : 'Copy transcript'}>
                    <Button size="small" variant="outlined" color={copiedTranscript ? 'success' : 'primary'} startIcon={<ContentCopyIcon />} onClick={() => {navigator.clipboard.writeText(transcript); setCopiedTranscript(true); setTimeout(() => setCopiedTranscript(false), 1500);}}>{copiedTranscript ? 'Đã copy' : 'Copy'}</Button>
                  </Tooltip>
                </Box>
                <Typography variant="body2" color="text.secondary" sx={{ whiteSpace: 'pre-wrap', maxHeight: 200, overflow: 'auto', fontSize: 15 }}>{transcript || 'Không có transcript'}</Typography>
              </Grid>
            </Grid>
          )}
          {/* Đã render context_analysis qua InvestigationSummaryCard, không cần lặp lại JSON */}
          {/* Nếu task là một bản tóm tắt tổng hợp (summary object), hiển thị rõ ràng */}
          {tab === 1 && task.type && (
            <Box mb={2}>
              <Chip label={task.type === 'case' ? 'Tóm tắt vụ việc' : 'Tóm tắt nhiều file'} color="secondary" sx={{ fontWeight: 700, fontSize: 15, mr: 2 }} />
              <Typography variant="caption" color="text.secondary">{task.created_at ? new Date(task.created_at).toLocaleString() : ''}</Typography>
              {task.case && (
                <Typography variant="body2" color="text.secondary">Vụ việc: {task.case.title}</Typography>
              )}
              {task.files && task.files.length > 0 && (
                <Typography variant="body2" color="text.secondary">File liên quan: {task.files.map(f => f.filename).join(', ')}</Typography>
              )}
              <Typography variant="body1" sx={{ whiteSpace: 'pre-wrap', mt: 1 }}>{task.content}</Typography>
              <Button variant="outlined" size="small" sx={{ mt: 1 }} onClick={() => navigator.clipboard.writeText(task.content ?? '')}>Copy nội dung</Button>
            </Box>
          )}
          <Box mt={3} display="flex" gap={2}>
            <Button variant="outlined" size="medium" color="primary" onClick={() => onEditContext(task)} sx={{ fontWeight: 600, borderRadius: 2 }} disabled={isEditingContext || isResummarizing}>
              Chỉnh sửa ngữ cảnh
            </Button>
            {task.status === 'processing' && (
              <Box display="flex" alignItems="center" gap={1}>
                <LinearProgress sx={{ width: 120, borderRadius: 2 }} />
                <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                  Đang xử lý file âm thanh...
                </Typography>
              </Box>
            )}
          </Box>
        </Box>
      </Collapse>
    </Paper>
  );
};

export default TaskListItem; 