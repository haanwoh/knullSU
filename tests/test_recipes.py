from __future__ import annotations

from pathlib import Path

import pytest

from plx import recipes


def test_bundled_recipes_discovered():
    catalog = recipes.discover()
    assert {"devbox", "datascience", "webdev", "minimal"} <= set(catalog)
    for path in catalog.values():
        assert path.exists()


def test_load_devbox():
    recipe = recipes.load(recipes.resolve("devbox"))
    assert recipe.name == "devbox"
    assert recipe.base == "ubuntu"
    assert "git" in recipe.packages["apt"]
    assert "web" in recipe.services
    assert recipe.hooks["post_install"]
    assert recipe.mounts


def test_resolve_unknown_name():
    with pytest.raises(recipes.RecipeError, match="no recipe named"):
        recipes.resolve("nope")


def test_load_invalid_toml(tmp_path: Path):
    bad = tmp_path / "bad.toml"
    bad.write_text("[recipe\nname=")
    with pytest.raises(recipes.RecipeError, match="invalid TOML"):
        recipes.load(bad)


def test_load_commandless_service(tmp_path: Path):
    bad = tmp_path / "bad.toml"
    bad.write_text('[recipe]\nname = "x"\n[services.s]\nrestart = "always"\n')
    with pytest.raises(recipes.RecipeError, match="command"):
        recipes.load(bad)


def test_load_minimal_defaults(tmp_path: Path):
    path = tmp_path / "plain.toml"
    path.write_text('[recipe]\nname = "plain"\n')
    recipe = recipes.load(path)
    assert recipe.packages == {} and recipe.services == {} and recipe.hooks == {}


def test_detect_package_manager(fake_rootfs: Path, cfg):
    assert recipes.detect_package_manager(cfg) == "apt"
    (fake_rootfs / "usr/bin/apt-get").unlink()
    assert recipes.detect_package_manager(cfg) is None


def test_apply_dry_run(cfg):
    recipe = recipes.load(recipes.resolve("devbox"))
    report = recipes.apply(recipe, cfg, dry_run=True)
    assert report["ok"] is True
    assert report["dry_run"] is True
    assert report["package_manager"] == "apt"
    assert any(step["step"] == "apt-update" for step in report["steps"])
    assert any(step["step"].startswith("hook") for step in report["steps"])


def test_apply_requires_rootfs(plx_home: Path, cfg):
    recipe = recipes.load(recipes.resolve("minimal"))
    cfg.core.rootfs = str(plx_home / "missing")
    with pytest.raises(recipes.RecipeError, match="no rootfs"):
        recipes.apply(recipe, cfg)


def test_apply_adds_services(cfg, plx_home: Path):
    recipe = recipes.load(recipes.resolve("minimal"))
    report = recipes.apply(recipe, cfg, dry_run=True, with_services=True)
    assert "sshd" in report["services_added"]


def test_copy_into_user_dir(plx_home: Path):
    source = recipes.resolve("minimal")
    target = recipes.copy_into_user_dir(source)
    assert target.exists() and target.parent == plx_home / "recipes"
