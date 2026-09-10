#!/usr/bin/env python3
"""Validate preparation against a local Android checkout without modifying it."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import tempfile


def run(*args, cwd=None, ok=True):
    result = subprocess.run(args, cwd=cwd, capture_output=True)
    if ok and result.returncode:
        raise RuntimeError(result.stderr.decode() + result.stdout.decode())
    return result


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("android", type=Path)
args = parser.parse_args()
manifest = Path(__file__).resolve().parents[2]
files = {
    "build/make": ["core/product_config.mk", "tools/releasetools/ota_from_target_files.py"],
    "system/sepolicy": ["vendor/hal_bootctl_default.te"],
    "packages/services/Car": ["car_product/build/car.mk", "car_product/build/car_system.mk"],
    "device/brcm/rpi5": ["aosp_rpi5_car.mk"],
    "device/generic/car": ["sdk_car_arm64.mk", "AndroidProducts.mk", "emulator/audio/driver/audio_hw.c", "emulator/car_emulator_vendor.mk"],
    "device/generic/goldfish": ["build/tasks.workaround/emu_img_zip.mk"],
}


def populate(root):
    run("git", "init", "-q", str(root))
    for project, names in files.items():
        for name in names:
            dest = root / project / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(run("git", "-C", str(args.android / project), "show", f"HEAD:{name}").stdout)


def digest(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file() and ".git" not in p.parts}


for scenario in ("fresh", "legacy-avd", "conflict"):
    with tempfile.TemporaryDirectory(prefix="caramel-prepare-test-") as temporary:
        root = Path(temporary)
        populate(root)
        if scenario == "legacy-avd":
            run("git", "apply", str(manifest / "tools/android17/caramel-avd/patches/0002-disable-stock-car-app-host-for-caramel.patch"), cwd=root)
        if scenario == "conflict":
            target = root / "packages/services/Car/car_product/build/car_system.mk"
            target.write_text(target.read_text().replace("    CarAppHost \\", "    UnexpectedHost \\", 1))
            before = digest(root)
            assert run("sh", str(manifest / "tools/android17/prepare-rpi5.sh"), str(root), ok=False).returncode != 0
            assert digest(root) == before
            print("PASS: conflicting host packaging rejected without edits")
            continue
        for script in ("prepare-rpi5.sh", "prepare-caramel-car-avd.sh"):
            run("sh", str(manifest / "tools/android17" / script), str(root))
        first = digest(root)
        for script in ("prepare-rpi5.sh", "prepare-caramel-car-avd.sh"):
            run("sh", str(manifest / "tools/android17" / script), str(root))
        second = digest(root)
        assert second == first, [name for name in second if second[name] != first.get(name)]
        for project, names in files.items():
            if project == "device/brcm/rpi5":
                continue  # Device source is committed separately, not patched here.
            for name in names:
                assert (root / project / name).read_bytes() == (args.android / project / name).read_bytes(), (scenario, project, name)
        for generated in (root / "device/generic/car/caramel-avd").rglob("*"):
            if generated.is_file():
                relative = str(generated.relative_to(root))
                expected = (args.android / relative).read_bytes()
                # Do not publish this exact build-local fake ownership stub.
                stub = b'\n// Build-local ownership metadata for an unused Cuttlefish VKMS module.\nteam {\n    name: "trendy_team_desktop_display",\n    trendy_team_id: "0",\n}\n'
                if relative == "device/generic/car/caramel-avd/Android.bp" and expected.endswith(stub):
                    expected = expected[:-len(stub)]
                assert generated.read_bytes() == expected, relative
        print(f"PASS: {scenario} preparation matches current Android checkout and is idempotent")
