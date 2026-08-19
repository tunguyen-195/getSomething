# Offline model manifests

Production model artifacts belong under the repository-local `models/` tree.
Every deployable model must have one `*.manifest.json` file under this
directory. The manifest pins the upstream revision, license, runtime backend,
artifact format, quantization, file sizes, and SHA-256 checksums.

`model-manifest.v1.example.json` documents the contract but is deliberately not
named `*.manifest.json`, so it is never treated as a deployed model. Validate a
packaged store without loading a model or using the network:

```powershell
.\venv\Scripts\python.exe scripts\model_store.py inventory
.\venv\Scripts\python.exe scripts\model_store.py preflight
```

The preflight fails closed when no production manifest is selected, a required
file is absent, a path escapes `models/`, or a size/checksum differs. Add model
licenses to the offline deployment bundle even when the manifest also records
an upstream license URL.
