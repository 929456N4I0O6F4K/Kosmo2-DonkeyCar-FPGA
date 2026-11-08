"""Simulate the PCA9685 bench on the actual open-drain RTL and a bus model."""
import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command, output, log):
    with log.open('w', encoding='utf-8') as stream:
        result = subprocess.run([str(x) for x in command], cwd=output,
                                stdout=stream, stderr=subprocess.STDOUT)
    text = log.read_text(encoding='utf-8', errors='replace')
    if result.returncode or 'FATAL:' in text or 'Fatal:' in text:
        raise RuntimeError(text[-8000:])
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vivado', type=Path, default=Path('C:/AMDDesignTools/2025.2/Vivado'))
    args = parser.parse_args()
    output = ROOT/'build/sim'
    output.mkdir(parents=True, exist_ok=True)
    bins = args.vivado/'bin'
    sources = [ROOT/'rtl/pca_i2c.v', ROOT/'rtl/pca_bench_core.v', *sorted((ROOT/'sim').glob('*.v'))]
    run([bins/'xvlog.bat', *sources], output, output/'compile.log')
    for top, marker in [('tb_pca_bench', 'ALL PCA BENCH TESTS PASS'),
                        ('tb_pca_esc', 'ALL PCA ESC TESTS PASS'),
                        ('tb_pca_recovery', 'ALL PCA RECOVERY TESTS PASS'),
                        ('tb_pca_frequency', 'ALL PCA FREQUENCY TESTS PASS'),
                        ('tb_pca_hold', 'ALL PCA HOLD TESTS PASS'),
                        ('tb_pca_joint', 'ALL PCA JOINT TESTS PASS')]:
        run([bins/'xelab.bat', top, '-s', top+'_sim', '-debug', 'typical'], output, output/(top+'_elaborate.log'))
        text = run([bins/'xsim.bat', top+'_sim', '-runall'], output, output/(top+'.log'))
        if marker not in text:
            raise RuntimeError(text[-8000:])
        print('\n'.join(line for line in text.splitlines() if 'PASS' in line))
    checks = dict(wire_level_read_write=True, boot_all_off=True, sleep_prescale_sequence=True,
                  configuration_readback=True, pulse_bounds=True, single_channel=True,
                  hardware_expiry=True, explicit_off=True, replay_and_retrigger_guard=True,
                  reset_with_powered_pca=True, nack=True, stuck_scl_sda=True,
                  fault_shutdown_retry=True, explicit_reinitialization_after_fault=True,
                  readback_mismatch=True, extended_range_steering_channel_only=True,
                  esc_neutral_dwell=True, esc_autonomous_phase_timing=True, esc_channel_isolation=True,
                  esc_no_signal_gap=True, esc_interrupt=True, esc_range_and_qualification=True,
                  esc_bus_fault_recovery=True, nine_clock_bus_clear=True,
                  recovery_aborts_actuator_command=True, interrupted_target_read_recovery=True,
                  persistent_short_not_reported_as_shutdown=True, first_bus_failure_retained=True,
                  pwm_50_60_selection=True, frequency_adjusted_bounds=True,
                  frequency_change_inhibits_replay=True, legacy_init_preserves_50hz=True,
                  hold_1_2_5_seconds=True, hold_fixed_calibrated_pair=True,
                  hold_autonomous_return_and_off=True, hold_interrupt_all_phases=True,
                  hold_retrigger_reset_bus_fault=True, legacy_duration_independent=True,
                  joint_pair_outputs_and_channel_isolation=True, joint_autonomous_phase_timing=True,
                  joint_neutral_qualification_and_fixed_limits=True, joint_no_signal_gap=True,
                  joint_off_retrigger_reset=True, joint_partial_write_fault_and_readback=True,
                  legacy_channel_isolation_after_joint=True,
                  joint_v8_steering_endpoints_and_interior=True,
                  joint_v9_steering_range_355_to_500_ticks=True,
                  joint_v9_steering_range_rejected_outside_bounds=True,
                  joint_v9_return_to_1745_center=True,
                  joint_v8_center_config_no_pwm_and_ack=True,
                  joint_v8_center_initial_and_return_match=True,
                  joint_v8_center_bounds_and_active_abort=True,
                  joint_v8_return_still_one_second=True)
    (output/'validation.json').write_text(json.dumps(checks, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
