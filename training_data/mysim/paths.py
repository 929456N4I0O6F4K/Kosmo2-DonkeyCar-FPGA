"""项目路径配置（相对定位，不依赖具体安装位置）"""
import os

# mysim/
MYSIM_DIR = os.path.dirname(os.path.realpath(__file__))
# car/
PROJECT_ROOT = os.path.dirname(MYSIM_DIR)

DATASETS_DIR = os.path.join(MYSIM_DIR, 'datasets')
SIM_DATA_DIR = os.path.join(DATASETS_DIR, 'sim')
MODELS_DIR = os.path.join(MYSIM_DIR, 'models')
REPORTS_DIR = os.path.join(MYSIM_DIR, 'reports')
ARTIFACTS_DIR = os.path.join(MYSIM_DIR, 'artifacts')
SCRIPTS_DIR = os.path.join(MYSIM_DIR, 'scripts')
DATA_DIR = os.path.join(MYSIM_DIR, 'data')

SIM_EXE = os.path.join(PROJECT_ROOT, 'DonkeySimLinux', 'donkey_sim.x86_64')
OFFICIAL_MODELS_DIR = os.path.join(PROJECT_ROOT, 'official_models')
FPGA_KIT_DIR = os.path.join(PROJECT_ROOT, 'fpga_dev_kit')

# 实车采集数据不在项目内，位置由环境变量 CAR_PHYSICAL_DATA 指定；
# 未指定时按以下候选顺序查找（含历史迁移位置）
PHYSICAL_DATA_DIR = os.environ.get('CAR_PHYSICAL_DATA') or next(
    (p for p in (
        os.path.join(os.path.dirname(PROJECT_ROOT), 'discarded_physical', '.discarded', 'physical'),
        os.path.join(os.path.dirname(PROJECT_ROOT), 'discarded_physical', 'physical'),
        os.path.join(PROJECT_ROOT, '.discarded', 'physical'),
    ) if os.path.isdir(p)),
    '',
)
