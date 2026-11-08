"""
自定义图像变换：真正的裁剪（非白色填充）+ 可选 CLAHE

Donkey Car 内置的 ImgCropMask 是白色填充（保留 120×160），
而裁剪版模型需要真正的裁剪（95×156 或 95×160）。

v2: 支持 CLAHE 预处理（与 mypilot1_s2_physical2_opt/opt2/opt3 训练一致）
    通过 myconfig.py 开关控制:
    CUSTOM_CROP_CLAHE = True          # 是否启用 (默认 False, 旧模型不受影响)
    CUSTOM_CROP_CLAHE_CLIP = 2.0      # clipLimit
    CUSTOM_CROP_CLAHE_TILE = 8        # tileGridSize (8×8)

用法（myconfig.py）:
    TRANSFORMATIONS = ['CUSTOM_CROP']
    CUSTOM_CROP_MODULE = '<mysim>/custom_crop.py'
    CUSTOM_CROP_CLASS = 'ImgRealCrop'
    ROI_CROP_TOP = 25
    ROI_CROP_LEFT = 2    # BRAM 优化版需要
    ROI_CROP_RIGHT = 2   # BRAM 优化版需要
    CUSTOM_CROP_CLAHE = True   # opt 系列模型必须开启
"""
import cv2


class ImgRealCrop:
    """真正裁剪图像顶部/底部/左/右，不填充; 可选 CLAHE (LAB-L 通道)"""

    def __init__(self, config):
        self.top = getattr(config, 'ROI_CROP_TOP', 0)
        self.bottom = getattr(config, 'ROI_CROP_BOTTOM', 0)
        self.left = getattr(config, 'ROI_CROP_LEFT', 0)
        self.right = getattr(config, 'ROI_CROP_RIGHT', 0)
        # CLAHE 配置 (opt 系列模型训练时使用, 推理必须一致)
        self.clahe_enable = bool(getattr(config, 'CUSTOM_CROP_CLAHE', False))
        clip = float(getattr(config, 'CUSTOM_CROP_CLAHE_CLIP', 2.0))
        tile = int(getattr(config, 'CUSTOM_CROP_CLAHE_TILE', 8))
        self.clahe = cv2.createCLAHE(clipLimit=clip, tileGridSize=(tile, tile)) \
            if self.clahe_enable else None

    def run(self, image):
        if image is None:
            return None
        h, w = image.shape[:2]
        top = self.top
        bottom = h - self.bottom if self.bottom > 0 else h
        left = self.left
        right = w - self.right if self.right > 0 else w
        img = image[top:bottom, left:right, ...]
        # CLAHE: 与训练管线一致 (裁剪后, 归一化前)
        if self.clahe is not None and img.ndim == 3 and img.shape[2] == 3:
            lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
            l, a, b = cv2.split(lab)
            l = self.clahe.apply(l)
            img = cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2RGB)
        return img

    def shutdown(self):
        pass
