from flask import Flask, render_template, request, jsonify
import json
from fontTools.ttLib import TTFont
from fontTools.pens.basePen import BasePen

app = Flask(__name__)

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

import traceback

def get_glyph_paths(font_path, text):
    font = TTFont(font_path, ignoreDecompileErrors=True)
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
                print(f"Error drawing glyph for {char}: {e}")
                traceback.print_exc()
            paths[char] = pen.path
    return paths

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_trajectories', methods=['POST'])
def get_trajectories():
    data = request.get_json()
    text = data.get('text', '山居秋暝')
    # You need to provide a path to a Chinese font file
    font_path = '/System/Library/Fonts/STHeiti Medium.ttc' # This is a common path on macOS
    try:
        paths = get_glyph_paths(font_path, text)
        return jsonify(paths)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=8008)
