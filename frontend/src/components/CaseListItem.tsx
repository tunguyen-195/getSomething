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
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import FolderIcon from '@mui/icons-material/Folder';
import TaskListItem from './TaskListItem';

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
}

interface Case {
  id: string;
  case_code: string;
  title: string;
  description?: string;
  tasks: Task[];
}

interface CaseListItemProps {
  caseItem: Case;
  isExpanded: boolean;
  onToggleExpand: (caseId: string) => void;
  selectedTasks: string[];
  onSelectTask: (taskId: string) => void;
  onDownloadTask: (task: Task) => void;
  onEditTaskContext: (task: Task) => void;
  editingTaskId: string | null;
  resummarizing: boolean;
  expandedTaskId: string | null;
  onToggleExpandTask: (taskId: string | null) => void;
  expandedSummaryId: string | null; // Pass down
  onToggleExpandSummary: (taskId: string | null) => void; // Pass down
}

const CaseListItem: React.FC<CaseListItemProps> = ({
  caseItem,
  isExpanded,
  onToggleExpand,
  selectedTasks,
  onSelectTask,
  onDownloadTask,
  onEditTaskContext,
  editingTaskId,
  resummarizing,
  expandedTaskId,
  onToggleExpandTask,
  expandedSummaryId,
  onToggleExpandSummary,
}) => {
  return (
    <Paper
      elevation={isExpanded ? 8 : 4}
      sx={{
        mb: 3,
        borderRadius: 2,
        boxShadow: isExpanded ? 4 : 2,
        background: isExpanded ? 'linear-gradient(135deg, #e3f2fd 0%, #fffde7 60%, #b9f6ca 100%)' : '#fff',
        border: '1px solid #e0e7ef',
        transition: 'box-shadow 0.3s, background 0.3s',
        ':hover': { boxShadow: 6, background: 'linear-gradient(90deg, #7c4dff 0%, #43e97b 100%)' },
      }}
    >
      <ListItem alignItems="flex-start" divider sx={{ p: 3 }} onClick={() => onToggleExpand(caseItem.id)} style={{ cursor: 'pointer' }}>
        <Grid container alignItems="center" spacing={3}>
          <Grid item>
            <FolderIcon 
              sx={{ 
                color: isExpanded ? '#ffd600' : '#fbc02d', 
                fontSize: 48, 
                transition: 'color 0.2s',
                cursor: 'pointer',
                '&:hover': { color: '#ffd600' }
              }} 
            />
          </Grid>
          <Grid item xs={12} sm={8} md={9}>
            <Typography fontWeight={700} fontSize={18}>{caseItem.title}</Typography>
            {caseItem.description && (
              <Typography variant="caption" color="text.secondary">
                {caseItem.description}
              </Typography>
            )}
            <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
              ({caseItem.tasks.length} file{caseItem.tasks.length !== 1 ? 's' : ''})
            </Typography>
          </Grid>
          <Grid item xs={12} sm={2} md={1}>
            <IconButton size="large" sx={{ color: '#1976d2' }}>
              {isExpanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
            </IconButton>
          </Grid>
        </Grid>
      </ListItem>
      <Collapse in={isExpanded} sx={{ width: '100%' }}>
        <Divider />
        <Box sx={{ p: 3, background: '#f0f4f8', borderRadius: '0 0 5px 5px' }}>
          {caseItem.tasks.length === 0 ? (
            <Typography variant="body2" color="text.secondary">Không có task nào trong vụ việc này.</Typography>
          ) : (
            caseItem.tasks.map(task => (
              <TaskListItem
                key={task.id}
                task={{
                  ...task,
                  summary: task.result?.summary,
                  transcript: task.result?.transcription,
                }}
                isSelected={selectedTasks.includes(task.id)}
                onSelect={onSelectTask}
                isExpanded={expandedTaskId === task.id}
                onToggleExpand={onToggleExpandTask}
                onDownload={onDownloadTask}
                onEditContext={onEditTaskContext}
                isEditingContext={editingTaskId === task.id}
                isResummarizing={resummarizing}
                expandedSummaryId={expandedSummaryId}
                onToggleExpandSummary={onToggleExpandSummary}
              />
            ))
          )}
        </Box>
      </Collapse>
    </Paper>
  );
};

export default CaseListItem; 