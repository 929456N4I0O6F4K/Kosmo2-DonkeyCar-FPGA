#!/bin/bash
# 交互式训练流水线
# 支持：手动带跑 → AI 自主驾驶 → 人工纠错 → 增量训练 → 重新测试
#
# 使用方法：
#   ./interactive_train.sh setup [model_name]     # 启动训练环境（模拟器 + Web 控制器）
#   ./interactive_train.sh train [model_name] [transfer_model]    # 训练/迁移学习
#   ./interactive_train.sh restart [model_name]  # 重启 manage.py drive（保持模拟器）
#   ./interactive_train.sh clean    # 清空数据（开始新一轮采集）
#   ./interactive_train.sh status   # 查看当前状态
#
# 环境变量（可选，覆盖 myconfig.py 中的默认值）：
#   DATA_PATH       数据保存路径（默认从 myconfig.py 读取）
#   MODELS_PATH     模型保存路径（默认从 myconfig.py 读取）

set -e

MYSIM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SIM_DIR="$(dirname "$MYSIM_DIR")/DonkeySimLinux"
CONDA_INIT="source $HOME/.miniforge3/etc/profile.d/conda.sh && conda activate donkey"

# 从 myconfig.py 读取全局路径变量
eval "$CONDA_INIT"
read_path_var() {
    python -c "
import sys, os
sys.path.insert(0, '$MYSIM_DIR')
import myconfig as cfg
print(getattr(cfg, '$1', os.path.join('$MYSIM_DIR', '$2')))
"
}
DATA_DIR="${DATA_PATH:-$(read_path_var DATA_PATH data)}"
MODELS_DIR="${MODELS_PATH:-$(read_path_var MODELS_PATH models)}"

echo "[路径配置] DATA_DIR=$DATA_DIR"
echo "[路径配置] MODELS_DIR=$MODELS_DIR"

# 查找模型文件：支持 .keras 和 .h5 两种扩展名
# 支持两种存放位置：
#   1. models/<name>.<ext>           （平铺在 MODELS_DIR 下）
#   2. models/<name>/<name>.<ext>（按模型名分子目录存放）
find_model_file() {
    local name="$1"
    local ext cm_dir
    # 1. 在 MODELS_DIR (models/) 查找
    for ext in keras h5; do
        if [ -f "${MODELS_DIR}/${name}.${ext}" ]; then
            echo "${MODELS_DIR}/${name}.${ext}"
            return 0
        fi
    done
    # 2. 在 models/<name>/ 子目录查找
    cm_dir="${MYSIM_DIR}/models/${name}"
    for ext in keras h5; do
        if [ -f "${cm_dir}/${name}.${ext}" ]; then
            echo "${cm_dir}/${name}.${ext}"
            return 0
        fi
    done
    # 未找到，输出空字符串
    return 0
}

case "$1" in
    setup)
        # 用法：./interactive_train.sh setup [model_name]
        #   model_name （可选）启动时加载的模型名（不带 .keras）。不指定则用 mypilot
        MODEL_NAME=${2:-mypilot}
        echo "=== 启动交互式训练环境（模型: $MODEL_NAME）==="

        # 检查并启动模拟器（图形模式，必须渲染图像）
        if ! pgrep -f "donkey_sim.x86_64" > /dev/null 2>&1; then
            echo "启动模拟器（图形模式）..."
            cd "$SIM_DIR"
            nohup ./donkey_sim.x86_64 > /dev/null 2>&1 &
            echo "等待模拟器就绪..."
            for i in $(seq 1 30); do
                if ss -tunap 2>/dev/null | grep -q ":9091.*LISTEN"; then
                    echo "模拟器已就绪 (端口 9091)"
                    break
                fi
                sleep 1
            done
        else
            echo "模拟器已在运行"
        fi

        # 启动 manage.py drive（带模型）
        if ! pgrep -f "manage.py drive" > /dev/null 2>&1; then
            echo "启动 Web 控制器..."
            eval "$CONDA_INIT"
            cd "$MYSIM_DIR"

            MODEL_FILE=$(find_model_file "$MODEL_NAME")
            if [ -n "$MODEL_FILE" ]; then
                echo "使用已有模型 $MODEL_FILE"
                nohup python manage.py drive --model "$MODEL_FILE" --type linear \
                    > /tmp/donkey_drive.log 2>&1 &
            else
                echo "未找到模型 '$MODEL_NAME'（已查找 models/，.keras 和 .h5）"
                echo "可用的模型:"
                ls -1 "$MODELS_DIR"/*.keras "$MODELS_DIR"/*.h5 2>/dev/null | sed 's/^/  /' || echo "  (models/ 下无模型)"
                for d in "$MYSIM_DIR"/models/*/; do
                    [ -d "$d" ] && ls -1 "$d"*.keras "$d"*.h5 2>/dev/null | sed 's/^/  /'
                done
                echo "以纯手动模式启动"
                nohup python manage.py drive > /tmp/donkey_drive.log 2>&1 &
            fi

            sleep 8
            if grep -q "drive your car" /tmp/donkey_drive.log 2>/dev/null; then
                echo "Web 控制器已就绪"
            else
                echo "等待 Web 控制器启动..."
                sleep 5
            fi
        else
            echo "manage.py drive 已在运行"
        fi

        echo ""
        echo "============================================================"
        echo "训练环境已就绪！"
        echo ""
        echo "浏览器打开: http://localhost:8887"
        echo ""
        echo "交互式训练流程："
        echo "  1. [第一阶段] 选 User 模式，用方向键带小车跑 3-5 圈"
        echo "     - 有油门时会自动录制数据"
        echo "     - 撞墙时立即松油门停止录制"
        echo ""
        echo "  2. [第二阶段] 切到 Local 模式，让 AI 自主驾驶"
        echo "     - 发现 AI 要撞墙时立即切回 User 模式接管"
        echo "     - 用方向键纠正方向，继续跑"
        echo "     - AI 驾驶时也会录制数据（已开启 RECORD_DURING_AI）"
        echo "     - 你纠正时的数据会训练 AI 如何从错误中恢复"
        echo ""
        echo "  3. [训练] 退出浏览器后运行:"
        echo "     ./interactive_train.sh train"
        echo ""
        echo "  4. [测试] 训练完后运行:"
        echo "     ./interactive_train.sh restart"
        echo "     然后浏览器选 Local 模式测试新模型"
        echo "============================================================"
        ;;

    train)
        # 用法：./interactive_train.sh train [model_name] [transfer_model]
        #   model_name       （可选）输出模型名，不带 .keras。不指定默认 mypilot
        #   transfer_model   （可选）迁移学习源模型路径。不指定则从头训练
        #
        # 示例：
        #   ./interactive_train.sh train                    # 从头训练 models/mypilot.keras
        #   ./interactive_train.sh train mypilot_v2          # 从头训练 models/mypilot_v2.keras
        #   ./interactive_train.sh train mypilot_fine ../official_models/2_circuit_launch_pilots/pilot_21-08-13_10.keras  # 迁移学习
        echo "=== 用所有采集的数据训练新模型 ==="
        eval "$CONDA_INIT"
        cd "$MYSIM_DIR"

        MODEL_NAME=${2:-mypilot}
        TRANSFER_MODEL=${3:-}
        OUTPUT_MODEL="${MODELS_DIR}/${MODEL_NAME}.keras"

        if [ -n "$TRANSFER_MODEL" ]; then
            echo "模式: 迁移学习（补充训练）"
            echo "  源模型: $TRANSFER_MODEL"
            echo "  输出模型: $OUTPUT_MODEL"
        else
            echo "模式: 从头训练"
            echo "  输出模型: $OUTPUT_MODEL"
        fi

        # 收集所有 tub 数据（兼容两种存储格式）
        TUBS=""
        if [ -f "$DATA_DIR/manifest.json" ]; then
            TUBS="$DATA_DIR/"
            echo "检测到 Tub v2 格式（manifest.json 在 $DATA_DIR 根目录）"
        fi
        SUB_TUBS=$(find "$DATA_DIR" -maxdepth 1 -name "tub_*" -type d 2>/dev/null | tr '\n' ' ')
        if [ -n "$SUB_TUBS" ]; then
            TUBS="$TUBS $SUB_TUBS"
        fi
        TUBS=$(echo "$TUBS" | tr ' ' '\n' | grep -v '^$' | sort -u | tr '\n' ' ')

        if [ -z "$TUBS" ]; then
            echo "错误：没有找到训练数据"
            echo "请先运行 ./interactive_train.sh setup 并采集数据"
            exit 1
        fi

        echo "找到的训练数据:"
        for tub in $TUBS; do
            if [ -f "$tub/manifest.json" ]; then
                count=$(python -c "
import json
count = 0
with open('$tub/manifest.json') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            m = json.loads(line)
            if isinstance(m, dict) and 'current_index' in m:
                count = m['current_index']
                break
        except:
            continue
print(count)
" 2>/dev/null)
                echo "  $tub: $count 条记录 (Tub v2)"
            elif [ -d "$tub/images/" ]; then
                count=$(ls "$tub/images/" 2>/dev/null | wc -l)
                echo "  $tub: $count 条记录"
            fi
        done

        echo ""
        echo "开始训练..."
        if [ -n "$TRANSFER_MODEL" ]; then
            donkey train --tub $TUBS --model "$OUTPUT_MODEL" --type linear --transfer "$TRANSFER_MODEL"
        else
            donkey train --tub $TUBS --model "$OUTPUT_MODEL" --type linear
        fi

        echo ""
        echo "训练完成！运行 ./interactive_train.sh restart $MODEL_NAME 测试新模型"
        ;;

    restart)
        # 用法：./interactive_train.sh restart [model_name]
        #   model_name （可选）要加载的模型名（不带 .keras）。不指定默认 mypilot
        MODEL_NAME=${2:-mypilot}
        echo "=== 重启 manage.py drive（测试模型: $MODEL_NAME）==="
        pkill -f "manage.py drive" 2>/dev/null || true
        sleep 3

        eval "$CONDA_INIT"
        cd "$MYSIM_DIR"

        MODEL_FILE=$(find_model_file "$MODEL_NAME")
        if [ -n "$MODEL_FILE" ]; then
            echo "加载模型 $MODEL_FILE"
            nohup python manage.py drive --model "$MODEL_FILE" --type linear \
                > /tmp/donkey_drive.log 2>&1 &
        else
            echo "未找到模型 '$MODEL_NAME'（已查找 models/，.keras 和 .h5）"
            echo "以纯手动模式启动"
            nohup python manage.py drive > /tmp/donkey_drive.log 2>&1 &
        fi

        sleep 10
        if pgrep -f "manage.py drive" > /dev/null 2>&1; then
            echo "manage.py drive 已重启"
            echo "浏览器打开 http://localhost:8887 选 Local 模式测试"
        else
            echo "启动失败，查看日志: cat /tmp/donkey_drive.log"
        fi
        ;;

    clean)
        echo "=== 清空训练数据 ==="
        pkill -f "manage.py drive" 2>/dev/null || true
        sleep 2
        # 清理 Tub v2 格式（catalog_*.catalog 和 manifest.json 直接在 $DATA_DIR 下）
        rm -f "$DATA_DIR/manifest.json"
        rm -f "$DATA_DIR/catalog_"*.catalog
        rm -f "$DATA_DIR/catalog_"*.catalog_manifest
        rm -rf "$DATA_DIR/images"
        # 清理旧版 tub_* 子目录
        rm -rf "$DATA_DIR"/tub_*
        mkdir -p "$DATA_DIR"
        echo "数据已清空 ($DATA_DIR)"
        echo "运行 ./interactive_train.sh setup 重新开始采集"
        ;;

    status)
        echo "=== 当前状态 ==="
        eval "$CONDA_INIT"
        echo "路径配置:"
        echo "  数据目录: $DATA_DIR"
        echo "  模型目录: $MODELS_DIR"
        echo ""
        echo "模拟器:"
        if pgrep -f "donkey_sim.x86_64" > /dev/null 2>&1; then
            echo "  运行中 (PID $(pgrep -f 'donkey_sim.x86_64' | head -1))"
            ss -tunap 2>/dev/null | grep ":9091" | head -3 | sed 's/^/  /'
        else
            echo "  未运行"
        fi

        echo "manage.py drive:"
        if pgrep -f "manage.py drive" > /dev/null 2>&1; then
            echo "  运行中 (PID $(pgrep -f 'manage.py drive' | head -1))"
            ss -tunap 2>/dev/null | grep ":8887" | head -3 | sed 's/^/  /'
        else
            echo "  未运行"
        fi

        echo "训练数据:"
        # Tub v2 格式：manifest.json 直接在 $DATA_DIR 下
        if [ -f "$DATA_DIR/manifest.json" ]; then
            count=$(python -c "
import json
count = 0
with open('$DATA_DIR/manifest.json') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            m = json.loads(line)
            if isinstance(m, dict) and 'current_index' in m:
                count = m['current_index']
                break
        except:
            continue
print(count)
" 2>/dev/null)
            echo "  $DATA_DIR (Tub v2): $count 条记录"
        fi
        # 旧版格式：tub_* 子目录
        for tub in "$DATA_DIR"/tub_*; do
            if [ -d "$tub" ]; then
                count=$(ls "$tub/images/" 2>/dev/null | wc -l)
                echo "  $tub: $count 条记录"
            fi
        done

        echo "模型:"
        DEFAULT_FILE=$(find_model_file "mypilot")
        if [ -n "$DEFAULT_FILE" ]; then
            stat -c "  默认模型 $DEFAULT_FILE: %s bytes, 修改时间 %y" "$DEFAULT_FILE"
        else
            echo "  无默认模型 (mypilot)"
        fi
        echo "所有模型 (models/):"
        ls -1 "$MODELS_DIR"/*.keras "$MODELS_DIR"/*.h5 2>/dev/null | sed 's/^/  /'
        for d in "$MYSIM_DIR"/models/*/; do
            [ -d "$d" ] && ls -1 "$d"*.keras "$d"*.h5 2>/dev/null | sed 's/^/  /'
        done
        ;;

    *)
        echo "用法: $0 {setup|train|restart|clean|status}"
        echo ""
        echo "命令说明:"
        echo "  setup    启动训练环境（模拟器 + Web 控制器）"
        echo "  train    用所有采集的数据训练新模型"
        echo "  restart  重启 manage.py drive（测试新模型）"
        echo "  clean    清空训练数据"
        echo "  status    查看当前状态"
        ;;
esac
