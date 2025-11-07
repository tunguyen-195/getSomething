console.log('=== DEBUGGING FILES (V2) TAB ===');

// Check if files state is populated
console.log('Files state:', window.files || 'Not accessible from console');

// Manual test: Fetch files for case_id=1
fetch('/api/v1/audio?case_id=1')
  .then(res => res.json())
  .then(data => {
    console.log('API Response:', data);
    console.log('Number of files:', data.length);
    if (data.length === 0) {
      console.warn('No files found for case_id=1. Upload files first in V1 tab.');
    }
  })
  .catch(err => console.error('API Error:', err));

// Check if FileCard component exists
console.log('FileCard component:', typeof FileCard !== 'undefined' ? 'Loaded' : 'Not loaded');
