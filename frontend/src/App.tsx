import React, { useEffect, useState } from 'react';
import { ThemeProvider, CssBaseline, Box, AppBar, Toolbar, Typography, Paper, Drawer, List, ListItem, ListItemText, Divider, IconButton, InputBase, Button, CircularProgress, Tabs, Tab, Dialog, DialogTitle, DialogContent, DialogActions, TextField, Accordion, AccordionSummary, AccordionDetails } from '@mui/material';
import { lightTheme, darkTheme } from './theme';
import DarkModeToggle from './components/DarkModeToggle';
import SearchIcon from '@mui/icons-material/Search';
import MenuIcon from '@mui/icons-material/Menu';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import FileTable from './components/FileTable';
import TranscriptPanel from './components/TranscriptPanel';

interface Case {
  id: string;
  case_code: string;
  title: string;
  description?: string;
  status_id?: string;
  priority_id?: string;
  created_by?: string;
  created_at?: string;
  summaries?: string[];
  transcripts?: string[];
}

const drawerWidth = 320;

function App() {
  const [mode, setMode] = useState<'light' | 'dark'>('light');
  const [cases, setCases] = useState<Case[]>([]);
  const [loadingCases, setLoadingCases] = useState(false);
  const [selectedCase, setSelectedCase] = useState<Case | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [search, setSearch] = useState('');
  const [tab, setTab] = useState(0);
  const [selectedFileId, setSelectedFileId] = useState<string | null>(null);
  const [createCaseOpen, setCreateCaseOpen] = useState(false);
  const [newCaseTitle, setNewCaseTitle] = useState('');
  const [newCaseDesc, setNewCaseDesc] = useState('');
  const [creatingCase, setCreatingCase] = useState(false);

  useEffect(() => {
    setLoadingCases(true);
    fetch('/api/v1/cases')
      .then(res => res.json())
      .then(data => {
        setCases(data);
        setLoadingCases(false);
        if (data.length > 0) setSelectedCase(data[0]);
      })
      .catch(() => setLoadingCases(false));
  }, []);

  const filteredCases = cases.filter(c =>
    c.title.toLowerCase().includes(search.toLowerCase()) ||
    c.case_code.toLowerCase().includes(search.toLowerCase())
  );

  const toggleMode = () => setMode(prev => (prev === 'light' ? 'dark' : 'light'));

  const handleCreateCase = () => {
    setCreatingCase(true);
    fetch('/api/v1/cases', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: newCaseTitle, description: newCaseDesc })
    })
      .then(res => res.json())
      .then(data => {
        setCases(prev => [data, ...prev]);
        setSelectedCase(data);
        setCreateCaseOpen(false);
        setNewCaseTitle('');
        setNewCaseDesc('');
        setCreatingCase(false);
      })
      .catch(() => setCreatingCase(false));
  };

  function highlightSummary(summary: string) {
    if (!summary) return null;
    const keywordRegex = /(\b(?:người|địa điểm|thời gian|quyết định|hành động|cảm xúc|chủ đề|thông tin nhạy cảm|thực thể|mục tiêu|kết quả|liên hệ|mối quan hệ|tên|số điện thoại|email|địa chỉ|sự kiện|vai trò|tóm tắt|key points|entities|privacy)\b)/gi;
    const blocks = summary.split(/\n|\r|\u2022|\-/).filter(Boolean);
    return (
      <Box>
        {blocks.map((block, idx) => (
          <Typography key={idx} variant="body1" sx={{ mb: 1, lineHeight: 1.7 }}>
            <span style={{ color: '#1976d2', fontWeight: 700, marginRight: 6 }}>•</span>
            {block.split(keywordRegex).map((part, i) =>
              keywordRegex.test(part) ? <b key={i} style={{ color: '#d32f2f' }}>{part}</b> : part
            )}
          </Typography>
        ))}
      </Box>
    );
  }

  return (
    <ThemeProvider theme={mode === 'light' ? lightTheme : darkTheme}>
      <CssBaseline />
      <AppBar position="fixed" sx={{ zIndex: 1300 }} color="primary" elevation={0}>
        <Toolbar>
          <IconButton edge="start" color="inherit" onClick={() => setSidebarOpen(!sidebarOpen)} sx={{ mr: 2 }}>
            <MenuIcon />
          </IconButton>
          <Typography variant="h6" sx={{ flexGrow: 1, fontWeight: 700 }}>
            Speech to Information
          </Typography>
          <DarkModeToggle mode={mode} toggleMode={toggleMode} />
        </Toolbar>
      </AppBar>
      <Drawer
        variant="persistent"
        open={sidebarOpen}
        sx={{
          width: drawerWidth,
          flexShrink: 0,
          '& .MuiDrawer-paper': {
            width: drawerWidth,
            boxSizing: 'border-box',
            background: mode === 'light' ? '#f8fafc' : '#23272f',
            borderRight: '1px solid #e0e7ef',
          },
        }}
      >
        <Toolbar />
        <Box sx={{ p: 2 }}>
          <Button
            variant="contained"
            color="primary"
            fullWidth
            sx={{ mb: 2, fontWeight: 700 }}
            onClick={() => setCreateCaseOpen(true)}
          >
            + Tạo Case mới
          </Button>
          <InputBase
            placeholder="Search cases..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            startAdornment={<SearchIcon sx={{ mr: 1 }} />}
            sx={{ width: '100%', mb: 2, px: 2, py: 1, borderRadius: 2, background: '#fff', boxShadow: 1 }}
          />
          <Divider sx={{ mb: 2 }} />
          {loadingCases ? (
            <Box display="flex" justifyContent="center" alignItems="center" height={120}>
              <CircularProgress />
            </Box>
          ) : (
            <List>
              {filteredCases.map(c => (
                <ListItem
                  button
                  key={c.id}
                  selected={selectedCase?.id === c.id}
                  onClick={() => setSelectedCase(c)}
                  sx={{ borderRadius: 2, mb: 1, bgcolor: selectedCase?.id === c.id ? 'primary.light' : undefined }}
                >
                  <ListItemText
                    primary={<Typography fontWeight={700}>{c.title}</Typography>}
                    secondary={<Typography variant="caption" color="text.secondary">{c.case_code}</Typography>}
                  />
                </ListItem>
              ))}
            </List>
          )}
        </Box>
      </Drawer>
      <Box sx={{ ml: sidebarOpen ? `${drawerWidth}px` : 0, transition: 'margin 0.3s', p: 4, pt: 10, minHeight: '100vh', bgcolor: 'background.default' }}>
        {selectedCase ? (
          <Paper elevation={3} sx={{ p: 4, borderRadius: 4 }}>
            <Typography variant="h5" fontWeight={700} mb={2}>Case: {selectedCase.title}</Typography>
            <Typography variant="body2" color="text.secondary" mb={1}>Code: {selectedCase.case_code}</Typography>
            {selectedCase.description && (
              <Typography variant="body1" color="text.primary" mb={2} sx={{ whiteSpace: 'pre-line' }}>
                {selectedCase.description}
              </Typography>
            )}
            <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
              <Tab label="Files" />
              <Tab label="Transcript" />
              <Tab label="Summary" />
              <Tab label="History" />
            </Tabs>
            {tab === 0 && <FileTable caseId={selectedCase.id} onSelectFile={setSelectedFileId} selectedFileId={selectedFileId} />}
            {tab === 1 && selectedFileId ? <TranscriptPanel fileId={selectedFileId} /> : tab === 1 ? (
              selectedCase && selectedCase.transcripts && selectedCase.transcripts.length > 0 ? (
                <Box>
                  <Typography variant="h6" fontWeight={700} mb={2}>Transcript các file</Typography>
                  {selectedCase.transcripts.map((t, idx) => (
                    <Accordion key={idx} defaultExpanded={idx === 0} sx={{ mb: 2 }}>
                      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                        <Typography fontWeight={600}>File {idx + 1}</Typography>
                      </AccordionSummary>
                      <AccordionDetails>
                        <Typography sx={{ whiteSpace: 'pre-line' }}>{t}</Typography>
                      </AccordionDetails>
                    </Accordion>
                  ))}
                </Box>
              ) : (
                <Typography color="text.secondary">Chưa có transcript nào cho vụ việc này.</Typography>
              )
            ) : null}
            {tab === 2 && (
              selectedCase && selectedCase.summaries && selectedCase.summaries.length > 0 ? (
                <Box>
                  <Typography variant="h6" fontWeight={700} mb={2}>Tóm tắt các file</Typography>
                  {selectedCase.summaries.map((s, idx) => (
                    <Accordion key={idx} defaultExpanded={idx === 0} sx={{ mb: 2 }}>
                      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                        <Typography fontWeight={600}>File {idx + 1}</Typography>
                      </AccordionSummary>
                      <AccordionDetails>
                        {highlightSummary(s)}
                      </AccordionDetails>
                    </Accordion>
                  ))}
                </Box>
              ) : (
                <Typography color="text.secondary">Chưa có tóm tắt nào cho vụ việc này.</Typography>
              )
            )}
            {tab === 3 && (
              <Typography color="text.secondary">Tính năng lịch sử thao tác sẽ được bổ sung sau.</Typography>
            )}
          </Paper>
        ) : (
          <Typography variant="h6" color="text.secondary">No case selected.</Typography>
        )}
      </Box>
      <Dialog open={createCaseOpen} onClose={() => setCreateCaseOpen(false)}>
        <DialogTitle>Tạo Case mới</DialogTitle>
        <DialogContent>
          <TextField
            label="Tên vụ việc"
            value={newCaseTitle}
            onChange={e => setNewCaseTitle(e.target.value)}
            fullWidth
            margin="normal"
            required
          />
          <TextField
            label="Mô tả"
            value={newCaseDesc}
            onChange={e => setNewCaseDesc(e.target.value)}
            fullWidth
            margin="normal"
            multiline
            minRows={2}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateCaseOpen(false)} disabled={creatingCase}>Huỷ</Button>
          <Button onClick={handleCreateCase} variant="contained" disabled={!newCaseTitle || creatingCase}>
            {creatingCase ? <CircularProgress size={20} /> : 'Tạo'}
          </Button>
        </DialogActions>
      </Dialog>
    </ThemeProvider>
  );
}

export default App; 