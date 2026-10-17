"""Download the pretrained assets needed for Chinese GPT-SoVITS v2 inference.

Place this script in the GPT-SoVITS project root, alongside the GPT_SoVITS folder,
then run: python down-model-v2.py
"""
from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from pathlib import Path

# Use the Hugging Face mirror by default. Set HF_ENDPOINT in your shell first
# if you prefer another endpoint.
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
print(f"Using Hugging Face endpoint: {os.environ['HF_ENDPOINT']}")

from huggingface_hub import hf_hub_download, snapshot_download

ROOT = Path(__file__).resolve().parent
PRETRAINED_DIR = ROOT / "GPT_SoVITS" / "pretrained_models"
TEXT_DIR = ROOT / "GPT_SoVITS" / "text"

REPO_ID = "lj1995/GPT-SoVITS"
ALLOW_PATTERNS = [
    # v2 inference weights (the discriminator s2D2333k.pth is not needed for inference)
    "gsv-v2final-pretrained/s1bert25hz-5kh-longer-epoch=12-step=369668.ckpt",
    "gsv-v2final-pretrained/s2G2333k.pth",
    # Shared text/audio feature models
    "chinese-hubert-base/**",
    "chinese-roberta-wwm-ext-large/**",
]


def download_v2_and_shared_models() -> None:
    PRETRAINED_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading v2 and shared models into: {PRETRAINED_DIR}")
    snapshot_download(
        repo_id=REPO_ID,
        allow_patterns=ALLOW_PATTERNS,
        local_dir=str(PRETRAINED_DIR),
    )
    print("v2 weights, HuBERT and RoBERTa download finished.")


def install_g2pw_model() -> None:
    """Download and unpack G2PWModel for Chinese text processing."""
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    target_dir = TEXT_DIR / "G2PWModel"

    if target_dir.is_dir() and any(target_dir.iterdir()):
        print(f"G2PWModel already exists; skipping: {target_dir}")
        return

    print("Downloading G2PWModel.zip for Chinese inference...")
    archive_path = Path(
        hf_hub_download(
            repo_id="XXXXRT/GPT-SoVITS-Pretrained",
            filename="G2PWModel.zip",
            repo_type="model",
        )
    )

    with tempfile.TemporaryDirectory(prefix="g2pw_extract_") as temp_dir:
        extract_root = Path(temp_dir) / "extracted"
        extract_root.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(archive_path, "r") as archive:
            root_resolved = extract_root.resolve()
            for member in archive.infolist():
                destination = (extract_root / member.filename).resolve()
                if destination != root_resolved and root_resolved not in destination.parents:
                    raise RuntimeError(f"Unsafe path in G2PW archive: {member.filename}")
            archive.extractall(extract_root)

        explicit_folder = extract_root / "G2PWModel"
        entries = [p for p in extract_root.iterdir() if p.name != "__MACOSX"]
        if explicit_folder.is_dir():
            source_dir = explicit_folder
        elif len(entries) == 1 and entries[0].is_dir():
            source_dir = entries[0]
        else:
            source_dir = extract_root

        if target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        for item in list(source_dir.iterdir()):
            if item.name == "__MACOSX":
                continue
            shutil.move(str(item), str(target_dir / item.name))

    if not any(target_dir.iterdir()):
        raise RuntimeError("G2PWModel was extracted but the target folder is empty.")
    print(f"G2PWModel installed at: {target_dir}")


def download_fasttext_model() -> None:
    """fast_langdetect 语种识别大模型(125MB)。

    langsegmenter.py:16 把 fast_langdetect 的 cache_dir 指向
    GPT_SoVITS/pretrained_models/fast_langdetect,缺了合成会报 pcm_synth_error
    (split_lang 的 detector.py:15 硬编码 model="full",不会用包内自带的 .ftz)。
    """
    target_dir = PRETRAINED_DIR / "fast_langdetect"
    target = target_dir / "lid.176.bin"
    if target.exists():
        print(f"fast_langdetect 模型已存在;跳过: {target}")
        return

    print("Downloading fast_langdetect lid.176.bin ...")
    target_dir.mkdir(parents=True, exist_ok=True)
    downloaded = hf_hub_download(
        repo_id="XXXXRT/GPT-SoVITS-Pretrained",
        filename="pretrained_models/fast_langdetect/lid.176.bin",
        repo_type="model",
    )
    shutil.copy2(downloaded, target)
    print(f"fast_langdetect 模型已安装: {target}")


def main() -> None:
    if not (ROOT / "GPT_SoVITS").is_dir():
        raise FileNotFoundError(
            "Place this script in the GPT-SoVITS project root (the folder containing GPT_SoVITS)."
        )

    download_v2_and_shared_models()
    install_g2pw_model()
    download_fasttext_model()

    print("\nAll requested model downloads finished.")
    print("For Chinese v2 inference, check GPT_SoVITS/configs/tts_infer.yaml paths.")
    print("Start the inference WebUI from the project root with:")
    print("  python GPT_SoVITS/inference_webui.py")


if __name__ == "__main__":
    main()
