# Copy models script
import shutil, os
from pathlib import Path
print('Copying models...')
src = Path(r'C:\Users\Admin\.cache\huggingface\hub')
dst = Path('models/pyannote')
dst.mkdir(parents=True, exist_ok=True)
for m in src.glob('models--pyannote*'):
    print(f'Copy: {m.name}')
    shutil.copytree(m, dst / m.name, dirs_exist_ok=True)
print('Done!')
