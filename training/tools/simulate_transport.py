"""Run the PA transport RTL testbench without programming a board."""
import json
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
out = root / "build" / "rtl-sim"
out.mkdir(parents=True, exist_ok=True)
bin_dir = Path("C:/AMDDesignTools/2025.2/Vivado/bin")
commands = [
    [bin_dir / "xvlog.bat", root / "rtl/kosmo_training_transport.v", root / "sim/tb_training_transport.v",
     root / "rtl/kosmo_training_camera.v", root / "rtl/kosmo_training_core.v", root / "sim/tb_training_camera.v",
     root / "board/axi32_sps64.v", root / "sim/tb_axi32_sps64.v",
     *[root.parent / "camera/rtl" / name for name in ("camera_capture.v", "camera_config.v", "camera_sccb.v", "camera_exposure.v", "ov2640_init_rom.v")]],
    [bin_dir / "xelab.bat", "tb_training_transport", "-s", "training_transport_sim", "-debug", "typical"],
    [bin_dir / "xsim.bat", "training_transport_sim", "-runall"],
    [bin_dir / "xelab.bat", "tb_training_camera", "-s", "training_camera_sim", "-debug", "typical"],
    [bin_dir / "xsim.bat", "training_camera_sim", "-runall"],
    [bin_dir / "xelab.bat", "kosmo_training_core", "-s", "training_core_elab"],
    [bin_dir / "xelab.bat", "tb_axi32_sps64", "-s", "width_sim"],
    [bin_dir / "xsim.bat", "width_sim", "-runall"],
]
transcript = ""
for i, command in enumerate(commands):
    with (out / f"{i}.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(list(map(str, command)), cwd=out, stdout=log, stderr=subprocess.STDOUT)
    text = (out / f"{i}.log").read_text(encoding="utf-8", errors="replace")
    if result.returncode or "FATAL" in text or "Fatal:" in text or "ERROR:" in text:
        raise RuntimeError(text[-6000:])
    transcript += text
if any(marker not in transcript for marker in ("ALL TRAINING TRANSPORT TESTS PASS", "ALL TRAINING CAMERA TESTS PASS", "ALL AXI WIDTH ADAPTER TESTS PASS")):
    raise RuntimeError(text[-6000:])
print(text[-2500:])
(out / "validation.json").write_text(json.dumps({"transport_rtl_simulation_passed": True, "camera_adapter_simulation_passed": True, "hardware_tested": False}, indent=2))
