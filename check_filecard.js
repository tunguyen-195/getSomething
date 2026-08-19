#!/usr/bin/env node
// Force check if FileCard has VIEW RESULTS in running app
const fs = require('fs');
const path = require('path');

const fileCardPath = path.join(__dirname, 'frontend', 'src', 'components', 'FileCard.tsx');
const content = fs.readFileSync(fileCardPath, 'utf8');

console.log('\n=== FILE CHECK ===');
console.log('Path:', fileCardPath);
console.log('Size:', fs.statSync(fileCardPath).size, 'bytes');
console.log('Has VIEW RESULTS:', content.includes('VIEW RESULTS'));
console.log('Has View Transcript button:', content.includes('View Transcript'));
console.log('Has View Summary button:', content.includes('View Summary'));
console.log('Line count:', content.split('\n').length);

if (content.includes('VIEW RESULTS')) {
    console.log('\n✅ FileCard.tsx source code is CORRECT!');
    console.log('Problem: Vite dev server not reloading the file');
    console.log('\nSolution:');
    console.log('1. Kill all node processes');
    console.log('2. Delete ALL cache folders');
    console.log('3. Start npm run dev');
    console.log('4. Wait for full compilation');
    console.log('5. Hard refresh browser (Ctrl+Shift+F5)');
} else {
    console.log('\n❌ FileCard.tsx source code is WRONG!');
}
