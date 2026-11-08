#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v5 合并脚本: 评估两个并行 trial 的 best (best_t1/best_t2), 同口径比较 val_loss
选优后调用 opt5.finalize_export 导出 (统一 best + FP32/INT8 量化 + TTA 评估 + 配置)

用法: python merge_trials_v5.py
注意: 本脚本不重新训练, 仅重建与训练完全一致的 val 集做评估与导出
"""
import os
import sys

import numpy as np
import tensorflow as tf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from train import train_s2_physical2_opt5 as opt5


def main():
    logger = opt5.logger
    logger.info("=" * 60)
    logger.info("v5 合并: 双 trial best 同口径评估 → 选优 → 导出")
    logger.info("=" * 60)

    # 1. 重建数据 (与训练 main() 完全一致的流程)
    logger.info("\n--- 重建数据管道 (与训练一致) ---")
    all_records, sessions = opt5.load_physic_records()
    straight_prev = opt5.load_straight_records_from_prev()
    all_records.extend(straight_prev)
    sessions.append(('physicdata(直行补充)', len(straight_prev)))
    all_records = opt5.clean_labels_pipeline(all_records)

    bins_count = [0] * 7
    for r in all_records:
        bins_count[opt5.get_bin_index(r.get('user/angle', 0))] += 1

    train_records, val_records = opt5.temporal_session_split(
        all_records, opt5.TEMPORAL_VAL_RATIO)
    logger.info(f"val_records: {len(val_records)} 条 (时间留出)")

    # 2. 加载并同口径评估两个 best (与训练验证完全一致: augment=False + WeightedMSE)
    val_gen = opt5.DataGeneratorEnhanced(
        val_records, batch_size=opt5.BATCH_SIZE, augment=False, seed=opt5.SEED + 1)

    candidates = []
    for i in (1, 2):
        p = f'{opt5.OUTPUT_DIR}/mypilot1_s2_physical_best_t{i}.keras'
        if not os.path.exists(p):
            logger.warning(f"跳过 (不存在): {p}")
            continue
        m = tf.keras.models.load_model(
            p, custom_objects={'WeightedMSE': opt5.WeightedMSE})
        m.compile(optimizer=tf.keras.optimizers.Adam(opt5.LEARNING_RATE_INIT),
                  loss=opt5.WeightedMSE(), metrics=['mae'], jit_compile=False)
        loss, mae = m.evaluate(val_gen, verbose=0)
        logger.info(f"Trial {i}: val_loss={loss:.6f}, val_mae={mae:.6f}  ({os.path.basename(p)})")
        candidates.append((float(loss), i, m))

    if not candidates:
        logger.error("未找到任何 best_t*.keras, 无法合并")
        sys.exit(1)

    candidates.sort(key=lambda c: c[0])
    best_loss, best_trial, best_model = candidates[0]
    logger.info(f"\n🏆 最优: Trial {best_trial} (val_loss={best_loss:.6f})")

    # 3. 导出 (统一 best + FP32/INT8 + TTA 评估 + 配置)
    trial_val_losses = {f'trial_{i}': l for l, i, _ in candidates}
    opt5.finalize_export(
        best_model, batch_size=opt5.BATCH_SIZE, epochs=opt5.EPOCHS,
        sessions=sessions, straight_prev=straight_prev,
        all_records=all_records, bins_count=bins_count,
        val_records=val_records, best_trial=best_trial,
        best_val_loss=best_loss, trial_val_losses=trial_val_losses)


if __name__ == '__main__':
    main()
