import React, { useState, useCallback, useRef } from 'react';
import {
    Box,
    Button,
    Typography,
    LinearProgress,
    Collapse,
    Paper,
    IconButton,
    Chip,
    List,
    ListItem,
    ListItemIcon,
    ListItemText,
    Menu,
    MenuItem,
    Tooltip,
} from '@mui/material';
import {
    CloudUpload as UploadIcon,
    Settings as SettingsIcon,
    ExpandMore as ExpandIcon,
    ExpandLess as CollapseIcon,
    AudioFile as AudioIcon,
    Delete as DeleteIcon,
    Close as CloseIcon,
    Check as CheckIcon,
} from '@mui/icons-material';
import { apiFetch } from '../api/client';

interface CompactUploaderProps {
    caseId: string;
    onUploadComplete?: () => void;
}

const CompactUploader: React.FC<CompactUploaderProps> = ({ caseId, onUploadComplete }) => {
    const [expanded, setExpanded] = useState(false);
    const [files, setFiles] = useState<File[]>([]);
    const [uploading, setUploading] = useState(false);
    const [uploadProgress, setUploadProgress] = useState(0);
    const [isDragging, setIsDragging] = useState(false);
    const inputRef = useRef<HTMLInputElement>(null);

    // Settings
    const [settingsAnchor, setSettingsAnchor] = useState<null | HTMLElement>(null);
    const [diarizationMethod, setDiarizationMethod] = useState('whisperx');
    const [fastMode, setFastMode] = useState(true);

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files) {
            setFiles(prev => [...prev, ...Array.from(e.target.files!)]);
            setExpanded(true);
        }
    };

    const handleDrop = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        setIsDragging(false);
        const dropped = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('audio/'));
        if (dropped.length > 0) {
            setFiles(prev => [...prev, ...dropped]);
            setExpanded(true);
        }
    }, []);

    const handleDragOver = (e: React.DragEvent) => {
        e.preventDefault();
        setIsDragging(true);
    };

    const handleDragLeave = () => setIsDragging(false);

    const removeFile = (idx: number) => {
        setFiles(prev => prev.filter((_, i) => i !== idx));
    };

    const handleUpload = async () => {
        if (files.length === 0 || !caseId) return;
        setUploading(true);
        setUploadProgress(0);

        try {
            for (let i = 0; i < files.length; i++) {
                const file = files[i];
                const formData = new FormData();
                formData.append('file', file);
                formData.append('case_id', caseId);
                formData.append('options', JSON.stringify({
                    language: 'auto',
                    fast_mode: fastMode,
                    enable_diarization: diarizationMethod !== 'none'
                }));
                formData.append('diarization_method', diarizationMethod);

                await apiFetch('/api/v1/audio/upload', {
                    method: 'POST',
                    body: formData,
                });

                setUploadProgress(((i + 1) / files.length) * 100);
            }

            setFiles([]);
            setExpanded(false);
            if (inputRef.current) inputRef.current.value = '';
            onUploadComplete?.();
        } catch (err) {
            console.error('Upload failed:', err);
        } finally {
            setUploading(false);
            setUploadProgress(0);
        }
    };

    const formatBytes = (bytes: number) => {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    };

    return (
        <Box>
            {/* Compact Bar */}
            <Box
                sx={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 1,
                    p: 1,
                    borderRadius: '12px',
                    bgcolor: expanded ? 'transparent' : 'rgba(225, 29, 72, 0.05)',
                    border: '1px solid',
                    borderColor: expanded ? 'primary.main' : 'divider',
                    transition: 'all 0.2s',
                }}
            >
                <input
                    ref={inputRef}
                    type="file"
                    accept="audio/*"
                    multiple
                    onChange={handleFileChange}
                    style={{ display: 'none' }}
                    id="compact-upload-input"
                />

                <label htmlFor="compact-upload-input">
                    <Button
                        component="span"
                        variant={expanded ? 'outlined' : 'contained'}
                        size="small"
                        startIcon={<UploadIcon />}
                        disabled={uploading}
                        sx={{
                            textTransform: 'none',
                            fontWeight: 600,
                            borderRadius: '8px',
                            px: 2,
                        }}
                    >
                        📤 Upload Audio
                    </Button>
                </label>

                {files.length > 0 && (
                    <Chip
                        label={`${files.length} file(s)`}
                        size="small"
                        color="primary"
                        onDelete={() => setFiles([])}
                    />
                )}

                <Box flex={1} />

                {/* Settings */}
                <Tooltip title="Cài đặt">
                    <IconButton
                        size="small"
                        onClick={(e) => setSettingsAnchor(e.currentTarget)}
                    >
                        <SettingsIcon fontSize="small" />
                    </IconButton>
                </Tooltip>

                <Menu
                    anchorEl={settingsAnchor}
                    open={Boolean(settingsAnchor)}
                    onClose={() => setSettingsAnchor(null)}
                >
                    <MenuItem
                        onClick={() => { setDiarizationMethod('whisperx'); }}
                        selected={diarizationMethod === 'whisperx'}
                    >
                        <CheckIcon sx={{ mr: 1, opacity: diarizationMethod === 'whisperx' ? 1 : 0 }} />
                        WhisperX (Speaker Detection)
                    </MenuItem>
                    <MenuItem
                        onClick={() => { setDiarizationMethod('none'); }}
                        selected={diarizationMethod === 'none'}
                    >
                        <CheckIcon sx={{ mr: 1, opacity: diarizationMethod === 'none' ? 1 : 0 }} />
                        No Speaker Detection
                    </MenuItem>
                    <MenuItem divider />
                    <MenuItem
                        onClick={() => { setFastMode(!fastMode); }}
                    >
                        <CheckIcon sx={{ mr: 1, opacity: fastMode ? 1 : 0 }} />
                        ⚡ Fast Mode
                    </MenuItem>
                </Menu>

                {/* Expand toggle */}
                <IconButton size="small" onClick={() => setExpanded(!expanded)}>
                    {expanded ? <CollapseIcon /> : <ExpandIcon />}
                </IconButton>
            </Box>

            {/* Expanded Section */}
            <Collapse in={expanded}>
                <Paper
                    sx={{
                        mt: 1,
                        p: 2,
                        borderRadius: '12px',
                        border: isDragging ? '2px dashed' : '1px solid',
                        borderColor: isDragging ? 'primary.main' : 'divider',
                        bgcolor: isDragging ? 'rgba(225, 29, 72, 0.05)' : 'background.paper',
                        transition: 'all 0.2s',
                    }}
                    onDrop={handleDrop}
                    onDragOver={handleDragOver}
                    onDragLeave={handleDragLeave}
                >
                    {files.length === 0 ? (
                        <Box textAlign="center" py={2}>
                            <Typography color="text.secondary" fontSize="0.9rem">
                                Kéo thả files vào đây hoặc click "Upload Audio"
                            </Typography>
                        </Box>
                    ) : (
                        <>
                            <List dense disablePadding>
                                {files.map((file, idx) => (
                                    <ListItem
                                        key={idx}
                                        secondaryAction={
                                            <IconButton size="small" onClick={() => removeFile(idx)}>
                                                <DeleteIcon fontSize="small" />
                                            </IconButton>
                                        }
                                        sx={{ py: 0.5 }}
                                    >
                                        <ListItemIcon sx={{ minWidth: 32 }}>
                                            <AudioIcon color="primary" fontSize="small" />
                                        </ListItemIcon>
                                        <ListItemText
                                            primary={file.name}
                                            secondary={formatBytes(file.size)}
                                            primaryTypographyProps={{ fontSize: '0.85rem', fontWeight: 500 }}
                                            secondaryTypographyProps={{ fontSize: '0.7rem' }}
                                        />
                                    </ListItem>
                                ))}
                            </List>

                            {uploading && (
                                <Box sx={{ mt: 2 }}>
                                    <LinearProgress variant="determinate" value={uploadProgress} />
                                    <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
                                        Uploading... {Math.round(uploadProgress)}%
                                    </Typography>
                                </Box>
                            )}

                            <Box display="flex" justifyContent="flex-end" mt={2} gap={1}>
                                <Button
                                    size="small"
                                    onClick={() => { setFiles([]); setExpanded(false); }}
                                    disabled={uploading}
                                >
                                    Cancel
                                </Button>
                                <Button
                                    variant="contained"
                                    size="small"
                                    onClick={handleUpload}
                                    disabled={uploading || files.length === 0}
                                    sx={{ textTransform: 'none', fontWeight: 600 }}
                                >
                                    {uploading ? 'Uploading...' : `Upload ${files.length} file(s)`}
                                </Button>
                            </Box>
                        </>
                    )}
                </Paper>
            </Collapse>
        </Box>
    );
};

export default CompactUploader;
