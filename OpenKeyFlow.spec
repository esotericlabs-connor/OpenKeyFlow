# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import tomllib

block_cipher = None

root_dir = Path(__file__).resolve().parent
metadata_path = root_dir / "openkeyflow.toml"

try:
    with metadata_path.open("rb") as handle:
        metadata = tomllib.load(handle)
except FileNotFoundError:
    metadata = {}

asset_entries = metadata.get("assets", {}).get("bundled", ["assets"])
datas = [(str(metadata_path), ".")]
for asset in asset_entries:
    asset_path = root_dir / asset
    datas.append((str(asset_path), asset))

a = Analysis(
    ["OpenKeyFlow.pyw"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="OpenKeyFlow",
    debug=False,
    strip=False,
    upx=True,
    console=False,
)