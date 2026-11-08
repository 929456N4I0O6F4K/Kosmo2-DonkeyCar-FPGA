import subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1]
out=root/'build/drive-sim';out.mkdir(parents=True,exist_ok=True)
bin=Path('C:/AMDDesignTools/2025.2/Vivado/bin')
for n,cmd in enumerate([
 [bin/'xvlog.bat',root/'rtl/pca_drive_core.v',root.parent/'actuators/rtl/pca_i2c.v',root.parent/'actuators/sim/pca9685_model.v',root/'sim/tb_pca_drive.v'],
 [bin/'xelab.bat','tb_pca_drive','-s','drive_sim','-debug','typical'],
 [bin/'xsim.bat','drive_sim','-runall']]):
 with (out/f'{n}.log').open('w') as f:result=subprocess.run(list(map(str,cmd)),cwd=out,stdout=f,stderr=subprocess.STDOUT)
 text=(out/f'{n}.log').read_text(errors='replace')
 if result.returncode or 'FATAL' in text or 'Fatal:' in text or 'ERROR:' in text:raise RuntimeError(text[-5000:])
if 'ALL CONTINUOUS PCA DRIVE TESTS PASS' not in text:raise RuntimeError(text[-5000:])
print(text[-1800:])
