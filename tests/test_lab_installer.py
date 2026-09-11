from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_bootstrap_targets_repository_installer() -> None:
    text = (ROOT / "bootstrap-xuhua.cmd").read_text("utf-8")
    assert "RinoPaw/xuhua/main/deploy/install-lab.ps1" in text
    assert "xuhua.env" in text


def test_installer_keeps_secrets_out_of_git() -> None:
    text = (ROOT / "deploy" / "install-lab.ps1").read_text("utf-8-sig")
    assert "xuhua.env" in text
    assert 'Destination (Join-Path $Project ".env")' in text
    assert "AI_API_KEY=" not in text
    assert "XF_API_SECRET=" not in text


def test_installer_does_not_download_unused_local_models() -> None:
    text = (ROOT / "deploy" / "install-lab.ps1").read_text("utf-8-sig")
    assert "models.manifest.json" not in text
    assert "huggingface_hub" not in text
    assert "SkipModels" not in text
