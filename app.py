from flask import Flask, render_template, request, jsonify
from fontTools.ttLib import TTFont
from fontTools.pens.basePen import BasePen
import traceback
import numpy as np
import pywt  # 导入 PyWavelets 库
import os    # 用于更稳健地处理字体路径

app = Flask(__name__)

# --- 字体路径查找逻辑 ---
# 尝试找到一个合适的中文字体
def find_font_path():
    if os.name == 'nt':  # Windows
        paths = [
            'C:/Windows/Fonts/msyh.ttc',      # 微软雅黑
            'C:/Windows/Fonts/simsun.ttc',      # 宋体
        ]
    elif os.name == 'posix':  # macOS 或 Linux
        paths = [
            '/System/Library/Fonts/STHeiti Medium.ttc',            # macOS 旧版
            '/System/Library/Fonts/Supplemental/STHeiti Medium.ttc', # macOS 新版
            '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', # Linux (Debian/Ubuntu)
            '/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.otf',     # Linux (Arch)
        ]
    else:
        paths = []
        
    for path in paths:
        if os.path.exists(path):
            print(f"使用的字体: {path}")
            return path
    
    # 如果没找到特定字体，则返回 None
    return None

FONT_PATH = find_font_path()

# --- 画笔和字形提取的类/函数 ---
class BezierPathPen(BasePen):
    def __init__(self, glyphSet):
        super().__init__(glyphSet)
        self.path = []

    def _moveTo(self, pt):
        self.path.append(("M", pt))

    def _lineTo(self, pt):
        self.path.append(("L", pt))

    def _curveToOne(self, pt1, pt2, pt3):
        self.path.append(("C", pt1, pt2, pt3))

    def _closePath(self):
        self.path.append(("Z",))

def get_glyph_paths(font_path, text):
    font = TTFont(font_path, fontNumber=0, ignoreDecompileErrors=True)
    glyphSet = font.getGlyphSet()
    cmap = font.getBestCmap()
    paths = {}
    for char in text:
        if ord(char) in cmap:
            glyphName = cmap[ord(char)]
            pen = BezierPathPen(glyphSet)
            try:
                glyphSet[glyphName].draw(pen)
            except Exception as e:
                print(f"绘制字形 '{char}' 时出错: {e}")
                traceback.print_exc()
            paths[char] = pen.path
    return paths

# --- 小波近似逻辑 ---
def approximate_path_with_wavelets(path, keep_ratio=0.2, wavelet='db4'):
    if not path:
        return []

    # 1. 将所有 x 和 y 坐标提取到单独的列表中
    x_coords, y_coords = [], []
    for segment in path:
        cmd = segment[0]
        if cmd in ('M', 'L'):
            x_coords.append(segment[1][0])
            y_coords.append(segment[1][1])
        elif cmd == 'C':
            for pt in segment[1:]:
                x_coords.append(pt[0])
                y_coords.append(pt[1])

    if not x_coords:  # 处理没有坐标的路径 (例如，只有一个 'Z' 命令)
        return path

    original_len = len(x_coords)
    
    # 确保坐标点数足够进行小波变换
    if original_len < pywt.Wavelet(wavelet).dec_len:
         return path # 数据太少，无法处理，返回原始路径

    # 2. 对 x 和 y 信号进行小波分解
    # 动态设置分解层数以获得最佳效果
    level = pywt.dwt_max_level(original_len, pywt.Wavelet(wavelet).dec_len)
    coeffs_x = pywt.wavedec(x_coords, wavelet, level=level)
    coeffs_y = pywt.wavedec(y_coords, wavelet, level=level)

    # 3. 对系数进行阈值处理
    def threshold_coeffs(coeffs, keep_ratio):
        all_coeffs_flat = np.concatenate([c.flatten() for c in coeffs])
        
        # 计算能保留 top `keep_ratio`% 系数的阈值
        k = int(len(all_coeffs_flat) * (1 - keep_ratio))
        if k >= len(all_coeffs_flat):
             threshold_val = np.max(np.abs(all_coeffs_flat)) + 1
        else:
             threshold_val = np.sort(np.abs(all_coeffs_flat))[k]

        thresholded = [pywt.threshold(c, threshold_val, mode='hard') for c in coeffs]
        return thresholded

    coeffs_x_thresh = threshold_coeffs(coeffs_x, keep_ratio)
    coeffs_y_thresh = threshold_coeffs(coeffs_y, keep_ratio)

    # 4. 从处理后的系数重构信号
    x_approx = pywt.waverec(coeffs_x_thresh, wavelet)
    y_approx = pywt.waverec(coeffs_y_thresh, wavelet)

    # 确保重构信号的长度与原始信号一致
    x_approx = x_approx[:original_len]
    y_approx = y_approx[:original_len]

    # 5. 用新的近似坐标重建路径
    reconstructed_path = []
    coord_idx = 0
    for segment in path:
        cmd = segment[0]
        if cmd == 'M' or cmd == 'L':
            if coord_idx < len(x_approx):
                pt = (x_approx[coord_idx], y_approx[coord_idx])
                reconstructed_path.append((cmd, pt))
                coord_idx += 1
        elif cmd == 'C':
            if coord_idx + 2 < len(x_approx):
                pt1 = (x_approx[coord_idx], y_approx[coord_idx])
                pt2 = (x_approx[coord_idx + 1], y_approx[coord_idx + 1])
                pt3 = (x_approx[coord_idx + 2], y_approx[coord_idx + 2])
                reconstructed_path.append((cmd, pt1, pt2, pt3))
                coord_idx += 3
        elif cmd == 'Z':
            reconstructed_path.append(segment)
            
    return reconstructed_path

# --- Flask 路由 ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_trajectories', methods=['POST'])
def get_trajectories():
    if not FONT_PATH:
         return jsonify({"error": "未在系统中找到合适的字体文件。请在 app.py 中更新 FONT_PATH。"}), 500

    data = request.get_json()
    text = data.get('text', '山居秋暝')
    # 从 UI 获取近似比例，如果未提供则默认为 0.2
    approximation_ratio = data.get('ratio', 0.2) 
    
    try:
        original_paths = get_glyph_paths(FONT_PATH, text)
        reconstructed_paths = {}
        for char, path in original_paths.items():
            reconstructed_paths[char] = approximate_path_with_wavelets(path, keep_ratio=approximation_ratio)

        return jsonify({
            "original": original_paths,
            "reconstructed": reconstructed_paths
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=8008)
