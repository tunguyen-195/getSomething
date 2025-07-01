import React, { useEffect, useState } from 'react';
import { ThemeProvider, CssBaseline, Box, AppBar, Toolbar, Typography, Paper, Drawer, List, ListItem, ListItemText, Divider, IconButton, InputBase, Button, CircularProgress, Tabs, Tab, Dialog, DialogTitle, DialogContent, DialogActions, TextField, Accordion, AccordionSummary, AccordionDetails } from '@mui/material';
import { lightTheme, darkTheme } from './theme';
import DarkModeToggle from './components/DarkModeToggle';
import SearchIcon from '@mui/icons-material/Search';
import CloseIcon from '@mui/icons-material/Close';
import AddIcon from '@mui/icons-material/Add';
import MenuIcon from '@mui/icons-material/Menu';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import FileTable from './components/FileTable';
import TranscriptPanel from './components/TranscriptPanel';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import FolderIcon from '@mui/icons-material/Folder';

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

function SummaryAccordionItem({ summary, idx, highlightSummary }: { summary: string, idx: number, highlightSummary: (s: string) => React.ReactNode }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    navigator.clipboard.writeText(summary);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <Accordion defaultExpanded={idx === 0} sx={{ mb: 2 }}>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Typography fontWeight={600}>File {idx + 1}</Typography>
      </AccordionSummary>
      <AccordionDetails>
        <Box display="flex" alignItems="center" mb={2}>
          <Button
            onClick={handleCopy}
            variant="outlined"
            color={copied ? 'success' : 'primary'}
            size="small"
            startIcon={<ContentCopyIcon />}
            sx={{ mr: 2 }}
          >
            {copied ? 'Đã copy' : 'Copy'}
          </Button>
          <Typography variant="body2" color="text.secondary">{copied ? 'Đã copy vào clipboard!' : ''}</Typography>
        </Box>
        {highlightSummary(summary)}
      </AccordionDetails>
    </Accordion>
  );
}

function App() {
  const [mode, setMode] = useState<'light' | 'dark'>('light');
  const [cases, setCases] = useState<Case[]>([]);
  const [loadingCases, setLoadingCases] = useState(false);
  const [selectedCase, setSelectedCase] = useState<Case | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [search, setSearch] = useState('');
  const [searchActive, setSearchActive] = useState(false);
  const [searchFocus, setSearchFocus] = useState(false);
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
      <AppBar position="fixed" sx={{ zIndex: 1300, bgcolor: mode === 'dark' ? '#2d2d34' : '#fff', backdropFilter: 'blur(12px)', boxShadow: '0 4px 24px #d32f2f22', borderBottom: '1.5px solid #ffd600' }} color="default" elevation={2}>
        <Toolbar sx={{ display: 'flex', alignItems: 'center', gap: 2, minHeight: 64, height: 64 }}>
          <IconButton edge="start" color="inherit" onClick={() => setSidebarOpen(!sidebarOpen)} sx={{ mr: 2 }}>
            <MenuIcon />
          </IconButton>
          <Box sx={{ height: 64, width: 160, display: 'flex', alignItems: 'center', justifyContent: 'center', mr: 3, flexShrink: 0, overflow: 'visible' }}>
            <img
              src={mode === 'dark' ? '/logo/white_on_trans.png' : '/logo/trans_bg.png'}
              alt="Cherry2 Logo"
              style={{
                height: '100%',
                width: '100%',
                maxHeight: 64,
                objectFit: 'contain',
                display: 'block',
                margin: 0,
                padding: 0,
                transform: 'scale(1.4)',
                transition: 'all 0.3s',
                overflow: 'visible',
                filter: mode === 'dark' ? 'drop-shadow(0 2px 8px #d32f2f88)' : 'none',
                opacity: 1,
              }}
            />
          </Box>
          <Box sx={{ display: 'flex', alignItems: 'center', minHeight: 64, height: 64, overflow: 'visible', flexGrow: 0 }}>
            <span style={{ fontWeight: 800, fontSize: 32, fontFamily: 'Poppins, Inter, Montserrat, Arial, sans-serif', letterSpacing: 1.5, textShadow: '0 2px 12px #d32f2f33', transition: 'color 0.8s', cursor: 'pointer', display: 'inline-block', maxWidth: 220, whiteSpace: 'nowrap', overflow: 'visible', textOverflow: 'ellipsis', color: '#d32f2f', flexShrink: 0, lineHeight: 1.1, verticalAlign: 'middle' }}>
              Cherry
              <span
                style={{
                  marginLeft: 4,
                  fontWeight: 900,
                  fontFamily: 'Poppins, Inter, Arial, sans-serif',
                  background: 'linear-gradient(90deg, #ffd600 0%, #d32f2f 40%, #ffb6c1 80%, #bdbdbd 100%)',
                  backgroundSize: '300% 100%',
                  WebkitBackgroundClip: 'text',
                  WebkitTextFillColor: 'transparent',
                  backgroundClip: 'text',
                  color: 'transparent',
                  border: 'none',
                  boxShadow: 'none',
                  outline: 'none',
                  padding: 0,
                  margin: 0,
                  display: 'inline-block',
                  fontSize: 48,
                  lineHeight: 1.1,
                  verticalAlign: 'middle',
                  overflow: 'visible',
                  animation: 'brand2-gradient-move 3.5s linear infinite',
                }}
              >
                2
              </span>
              <style>{`
                @keyframes brand2-gradient-move {
                  0% { background-position: 0% 50%; }
                  100% { background-position: 100% 50%; }
                }
              `}</style>
            </span>
          </Box>
          <Box sx={{ flexGrow: 1 }} />
          <Box sx={{ bgcolor: mode === 'dark' ? '#23272f' : '#fff', borderRadius: 2, px: 0.5, py: 0.5, boxShadow: mode === 'dark' ? '0 2px 8px #d32f2f22' : 'none', display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'background 0.3s' }}>
            <DarkModeToggle mode={mode} toggleMode={toggleMode} />
          </Box>
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
            background: mode === 'dark' ? '#2d2d34' : '#fff',
            borderRight: 'none',
            borderRadius: '0 20px 20px 0',
            boxShadow: mode === 'dark' ? '12px 0 48px #d32f2f33' : '12px 0 48px #d32f2f11',
            padding: '20px 0',
            transition: 'background 0.4s',
            '::-webkit-scrollbar': {
              width: 8,
              background: mode === 'dark' ? '#23272f' : '#f8fafc',
              borderRadius: 8,
            },
            '::-webkit-scrollbar-thumb': {
              background: mode === 'dark' ? '#d32f2f' : '#ffb6c1',
              borderRadius: 8,
              minHeight: 40,
              border: mode === 'dark' ? '2px solid #23272f' : '2px solid #fff',
            },
            '::-webkit-scrollbar-thumb:hover': {
              background: mode === 'dark' ? '#ffb6c1' : '#d32f2f',
              border: mode === 'dark' ? '2px solid #23272f' : '2px solid #fff',
            },
            '::-webkit-scrollbar-corner': {
              background: 'transparent',
            },
            scrollbarWidth: 'thin',
            scrollbarColor: mode === 'dark' ? '#ffb6c1 #23272f' : '#d32f2f #f8fafc',
          },
        }}
      >
        <Toolbar />
        <Box sx={{ p: 0, mt: 4, display: 'flex', flexDirection: 'column', gap: 1.2 }}>
          {/* Sidebar Action Group: Tạo Case mới + Search */}
          <Box sx={{
            display: 'flex', flexDirection: 'column', alignItems: 'center', width: '100%',
            bgcolor: 'background.paper',
            borderRadius: 0.75,
            boxShadow: mode === 'dark' ? '0 1px 6px #d32f2f22' : '0 1px 6px #d32f2f11',
            py: 0.7, px: 1, mb: 0.5,
            border: mode === 'dark' ? '1px solid #616161' : '1px solid #e0e7ef',
            position: 'sticky',
            top: 0,
            zIndex: 10,
            gap: 1.2,
          }}>
            <Button
              variant="contained"
              color="primary"
              sx={{
                fontWeight: 700,
                borderRadius: 2,
                fontSize: 15,
                py: 1,
                px: 2,
                minWidth: 0,
                width: '100%',
                height: 40,
                textTransform: 'none',
                letterSpacing: 1.1,
                transition: 'background 0.2s',
                display: 'flex',
                alignItems: 'center',
                gap: 1,
                mb: 0,
                boxShadow: '0 2px 8px #d32f2f22',
                color: '#fff',
                '&:hover': {
                  background: '#b71c1c',
                  color: '#fff',
                },
              }}
              onClick={() => setCreateCaseOpen(true)}
              startIcon={<AddIcon sx={{ fontSize: 20 }} />}
            >
              <span style={{ whiteSpace: 'nowrap' }}>Tạo Case</span>
            </Button>
            <Box
              sx={{
                position: 'relative',
                width: searchActive ? '100%' : 40,
                height: 40,
                border: '1.5px solid #e0e7ef',
                borderRadius: 2,
                background: '#f8fafc',
                boxShadow: '0 1px 8px #d32f2f11',
                display: 'flex',
                alignItems: 'center',
                px: searchActive ? 1 : 0,
                transition: 'all 0.25s cubic-bezier(.4,2,.6,1)',
                overflow: 'hidden',
                cursor: 'pointer',
                mt: '2px',
              }}
              onClick={() => { if (!searchActive) { setSearchActive(true); setSearchFocus(true); } }}
              onBlur={() => { setSearchFocus(false); setSearchActive(false); }}
              tabIndex={0}
            >
              {!searchActive && (
                <IconButton size="small" sx={{ ml: 0.5, color: '#bdbdbd' }}>
                  <SearchIcon />
                </IconButton>
              )}
              {searchActive && (
                <>
                  <SearchIcon sx={{ mr: 1, color: '#bdbdbd', transition: 'color 0.2s' }} />
                  <InputBase
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                    onFocus={() => setSearchFocus(true)}
                    onBlur={() => setSearchFocus(false)}
                    placeholder="Tìm kiếm case..."
                    sx={{ flex: 1, background: 'none', minWidth: 70, fontSize: 15, fontWeight: 500, outline: 'none', color: '#23272f' }}
                    autoFocus
                  />
                  {search && (
                    <IconButton size="small" sx={{ ml: 0.5, color: '#bdbdbd' }} onClick={e => { e.stopPropagation(); setSearch(''); }}>
                      <CloseIcon />
                    </IconButton>
                  )}
                </>
              )}
            </Box>
          </Box>
          <Divider sx={{ mb: 2 }} />
          {loadingCases ? (
            <Box display="flex" justifyContent="center" alignItems="center" height={120}>
              <CircularProgress />
            </Box>
          ) : (
            <List sx={{ px: 1, gap: 1 }}>
              {filteredCases.map(c => (
                <ListItem
                  button
                  key={c.id}
                  selected={selectedCase?.id === c.id}
                  onClick={() => setSelectedCase(c)}
                  sx={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: 1.2,
                    borderRadius: 1.2,
                    mb: 1,
                    px: 1.5,
                    py: 1,
                    minHeight: 56,
                    bgcolor: selectedCase?.id === c.id ? (mode === 'dark' ? '#ffb6c1' : '#fff') : (mode === 'dark' ? '#2d2d34' : '#fff'),
                    color: selectedCase?.id === c.id ? (mode === 'dark' ? '#d32f2f' : '#d32f2f') : 'text.primary',
                    boxShadow: selectedCase?.id === c.id ? (mode === 'dark' ? '0 4px 18px #d32f2f44' : '0 4px 18px #d32f2f11') : '0 1px 2px #ffb6c111',
                    border: selectedCase?.id === c.id ? (mode === 'dark' ? '1.5px solid #ffd600' : '1.5px solid #ffd600') : (mode === 'dark' ? '1.5px solid #616161' : '1.5px solid #e0e7ef'),
                    transition: 'all 0.18s cubic-bezier(.4,2,.6,1)',
                    '&:hover': {
                      background: mode === 'dark' ? '#d32f2f22' : '#ffb6c122',
                      border: '1.5px solid #d32f2f',
                      boxShadow: '0 8px 32px #d32f2f22',
                    },
                    '&.Mui-selected, &.Mui-selected:hover': {
                      background: mode === 'dark' ? '#ffb6c1' : '#fff',
                      border: mode === 'dark' ? '1.5px solid #ffd600' : '1.5px solid #ffd600',
                      boxShadow: mode === 'dark' ? '0 4px 18px #d32f2f44' : '0 4px 18px #d32f2f22',
                      color: '#d32f2f',
                    },
                  }}
                >
                  <Box sx={{ width: 40, height: 40, borderRadius: '8px', bgcolor: '#ffd6e0', display: 'flex', alignItems: 'center', justifyContent: 'center', mr: 1.5, boxShadow: '0 2px 8px #ffd60033', cursor: 'pointer', '&:hover svg': { color: '#ffd600' } }}>
                    <FolderIcon sx={{ color: selectedCase?.id === c.id ? '#ffd600' : '#43a047', fontSize: 32, transition: 'color 0.2s' }} />
                  </Box>
                  <ListItemText
                    primary={<Typography fontWeight={700} fontSize={15} color={selectedCase?.id === c.id ? '#d32f2f' : 'text.primary'} sx={{ wordBreak: 'break-word', whiteSpace: 'normal', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 180, lineHeight: 1.4 }}>{c.title}</Typography>}
                    secondary={c.description ? <Typography variant="caption" color="text.secondary" fontWeight={500} fontSize={13} letterSpacing={0.1} sx={{ wordBreak: 'break-word', whiteSpace: 'normal', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 180, lineHeight: 1.4 }}>{c.description}</Typography> : null}
                  />
                </ListItem>
              ))}
            </List>
          )}
        </Box>
      </Drawer>
      <Box sx={{ ml: sidebarOpen ? `${drawerWidth}px` : 0, transition: 'margin 0.3s', p: 4, pt: 8, minHeight: '100vh', bgcolor: 'background.default' }}>
        {selectedCase ? (
          <Paper elevation={3} sx={{
            p: { xs: 2, sm: 4 },
            borderRadius: { xs: 2, sm: 4 },
            mt: 6,
            background: mode === 'dark'
              ? 'linear-gradient(135deg, #23272f 0%, #2e2e3a 100%)'
              : '#fff',
            boxShadow: mode === 'dark'
              ? '0 8px 32px #7c4dff33'
              : '0 4px 24px #b388ff18',
            border: mode === 'dark'
              ? '1.5px solid #7c4dff'
              : '1px solid #e0e7ef',
            maxWidth: 900,
            margin: '40px auto 0 auto',
            color: mode === 'dark' ? 'text.primary' : undefined,
          }}>
            <Typography variant="h5" fontWeight={700} mb={2} sx={{ color: mode === 'dark' ? 'text.primary' : '#1976d2' }}>
              Case: {selectedCase.title}
            </Typography>
            {selectedCase.description && (
              <Typography variant="body1" mb={2} sx={{ color: mode === 'dark' ? 'text.secondary' : 'text.primary', whiteSpace: 'pre-line' }}>
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
                    <SummaryAccordionItem key={idx} summary={s} idx={idx} highlightSummary={highlightSummary} />
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
          <Button
            onClick={() => setCreateCaseOpen(false)}
            variant="outlined"
            color="primary"
            sx={{
              borderRadius: '12px',
              fontWeight: 700,
              textTransform: 'none',
              px: 3,
              py: 1.2,
              mr: 1.5,
              borderWidth: 2,
              '&:hover': {
                borderColor: 'primary.dark',
                color: 'primary.dark',
              },
            }}
            disabled={creatingCase}
          >
            Huỷ
          </Button>
          <Button
            onClick={handleCreateCase}
            variant="contained"
            color="primary"
            sx={{
              borderRadius: '12px',
              fontWeight: 700,
              textTransform: 'none',
              px: 3,
              py: 1.2,
              boxShadow: '0 2px 8px #b388ff22',
              '&:hover': {
                background: 'primary.dark',
                color: '#fff',
              },
            }}
            disabled={!newCaseTitle || creatingCase}
          >
            {creatingCase ? <CircularProgress size={20} /> : 'Tạo'}
          </Button>
        </DialogActions>
      </Dialog>
    </ThemeProvider>
  );
}

export default App; 