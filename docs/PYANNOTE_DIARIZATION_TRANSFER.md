# Pyannote Diarization Transfer

Tai lieu nay dung khi may dich khong co Internet/Hugging Face token nhung can bat tab
`Diarization` sau khi transcript.

## Model dang dung

- Primary model: `pyannote/speaker-diarization-community-1`
- Manifest id: `pyannote_community_1`
- Revision: `3533c8cf8e369892e6b79ff1bf80f7b0286a54ee`
- Host path trong repo: `models/pyannote/pyannote--speaker-diarization-community-1`
- Docker path: `/app/models/pyannote/pyannote--speaker-diarization-community-1`

Nhung file bat buoc:

- `config.yaml`
- `embedding/pytorch_model.bin`
- `plda/plda.npz`
- `plda/xvec_transform.npz`
- `segmentation/pytorch_model.bin`

Fallback `pyannote/speaker-diarization-3.1` dang la env fallback cu, nhung chua duoc
pin trong `docs/model_artifacts.required.json`, nen khong duoc dung lam goi offline chuan.

## Tao goi zip tren may co model

May tao goi can co `HF_TOKEN` hop le va da accept dieu kien model tren Hugging Face.

```powershell
cd D:\Workspace\SpeechToInfomation-pr
python download_pyannote_model.py
python scripts\verify_models.py --profile lite_rtx2050 --include-optional
python scripts\pack_pyannote_model.py
```

File zip se nam o:

```text
dist\model-bundles\pyannote_community_1_3533c8cf.zip
```

Neu script bao `pyannote_model_not_ready`, nghia la may nay chua co du model Pyannote
de dong goi. Hay chay lai `python download_pyannote_model.py` tren may co Internet/token,
hoac copy san thu muc model dung revision vao `models\pyannote` roi pack lai.

## Copy sang may dich

Copy zip sang may dich, vi du:

```text
C:\Users\Admin\Downloads\pyannote_community_1_3533c8cf.zip
```

Giai nen vao root repo:

```powershell
cd D:\Workspace\SpeechToInfomation-pr
Expand-Archive C:\Users\Admin\Downloads\pyannote_community_1_3533c8cf.zip -DestinationPath . -Force
```

Sau khi giai nen, kiem tra co file nay:

```powershell
Test-Path .\models\pyannote\pyannote--speaker-diarization-community-1\config.yaml
```

Restart Docker:

```powershell
docker compose --env-file .env up -d --build
```

Smoke check backend co load duoc Pyannote hay khong:

```powershell
docker compose exec backend python3 -c "from src.services.transcription.models.pyannote_manager import get_pyannote_manager; print(get_pyannote_manager().is_available())"
```

Ket qua mong doi khi co model dung: `True`.

## Neu chua copy duoc model

Code moi van cho bat Diarization tren UI. Backend se thu Pyannote truoc; neu Pyannote
thieu model hoac load fail, backend fallback sang `SimpleVAD`. Ket qua fallback co speaker
label de hien thi tab Diarization, nhung do chinh xac kem Pyannote va can review lai.
