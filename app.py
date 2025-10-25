from flask import Flask, render_template, request, jsonify
import json
from fontTools.ttLib import TTFont
from fontTools.pens.basePen import BasePen
import traceback
from transformers import AutoProcessor
import numpy as np

app = Flask(__name__)

# Load FAST+ processor
processor = AutoProcessor.from_pretrained("physical-intelligence/fast", trust_remote_code=True)

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
                print(f"Error drawing glyph for {char}: {e}")
                traceback.print_exc()
            paths[char] = pen.path
    return paths

def pathToNumpy(path):
    # Find the maximum number of points in a segment
    max_pts = 0
    for segment in path:
        max_pts = max(max_pts, len(segment) - 1)

    # Create a numpy array
    np_path = []
    for segment in path:
        segment_type = segment[0]
        pts = segment[1:]
        row = []
        if segment_type == 'M':
            row.extend([1,0,0,0])
        elif segment_type == 'L':
            row.extend([0,1,0,0])
        elif segment_type == 'C':
            row.extend([0,0,1,0])
        elif segment_type == 'Z':
            row.extend([0,0,0,1])
        
        for p in pts:
            row.extend(p)
        
        # Pad with zeros
        row.extend([0] * (2 * (max_pts - len(pts))))
        np_path.append(row)

    return np.array(np_path, dtype=np.float32)

def numpyToPath(np_path):
    """
    Converts a 2D numpy array back to a list of path commands.
    """
    path = []
    # np_path is expected to be a 2D array of shape (sequence_length, features)
    for row in np_path:
        # Find the most likely command by finding the index of the max value in the first 4 elements
        command_index = np.argmax(row[:4])
        
        if command_index == 0: # 'M'
            path.append(("M", (row[4], row[5])))
        elif command_index == 1: # 'L'
            path.append(("L", (row[4], row[5])))
        elif command_index == 2: # 'C'
            path.append(("C", (row[4], row[5]), (row[6], row[7]), (row[8], row[9])))
        elif command_index == 3: # 'Z'
            path.append(("Z",))
    return path

def normalize_path(np_path):
    """
    Normalizes the coordinates in a numpy path array to the [0, 1] range.
    Returns the normalized path, offset, and scale factor.
    """
    # We only care about coordinate columns (from index 4 onwards)
    coords = np_path[:, 4:]

    # Create a mask to ignore padding zeros
    # A row is padding if the command is all zeros (which shouldn't happen, but good practice)
    # or if the points are all zeros. A simpler way is to find non-zero elements.
    non_zero_mask = coords != 0
    if not np.any(non_zero_mask):
        # This path has no coordinates, return as is
        return np_path, np.array([0., 0.]), 1.0

    # Get all valid (non-zero) coordinates
    valid_coords = coords[non_zero_mask]

    # We need to separate x and y. X coords are at even indices, Y at odd.
    x_coords = coords[:, 0::2][non_zero_mask[:, 0::2]]
    y_coords = coords[:, 1::2][non_zero_mask[:, 1::2]]

    min_x, max_x = x_coords.min(), x_coords.max()
    min_y, max_y = y_coords.min(), y_coords.max()

    offset = np.array([min_x, min_y])
    scale = max(max_x - min_x, max_y - min_y)

    if scale == 0:
        scale = 1.0  # Avoid division by zero for single-point paths

    normalized_path = np_path.copy()
    # Apply normalization to coordinate columns
    for i in range(4, normalized_path.shape[1], 2):
        # Only apply to non-zero values to avoid affecting padding
        mask = normalized_path[:, i] != 0
        normalized_path[mask, i] = (normalized_path[mask, i] - offset[0]) / scale
        normalized_path[mask, i+1] = (normalized_path[mask, i+1] - offset[1]) / scale

    return normalized_path, offset, scale

def denormalize_path(normalized_path, offset, scale):
    """Denormalizes a numpy path array using the given offset and scale."""
    denormalized_path = normalized_path.copy()
    denormalized_path[:, 4:] = denormalized_path[:, 4:] * scale + np.tile(offset, int(denormalized_path.shape[1] / 2) - 2)
    return denormalized_path

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_trajectories', methods=['POST'])
def get_trajectories():
    data = request.get_json()
    text = data.get('text', '山居秋暝')
    font_path = '/System/Library/Fonts/STHeiti Medium.ttc'
    try:
        original_paths = get_glyph_paths(font_path, text)

        reconstructed_paths = {}
        for char, path in original_paths.items():
            # Convert path to numpy array
            np_path = pathToNumpy(path)

            # Normalize the path and store parameters for denormalization
            np_path_normalized, offset, scale = normalize_path(np_path)
            
            # Tokenize and detokenize
            tokens = processor([np_path_normalized])
            # The decoded path is also normalized
            decoded_normalized_path = processor.decode(tokens)[0]

            # Denormalize the path to get back original coordinates
            decoded_path = denormalize_path(decoded_normalized_path, offset, scale)
            
            # Convert back to path
            reconstructed_paths[char] = numpyToPath(decoded_path)

        return jsonify({
            "original": original_paths,
            "reconstructed": reconstructed_paths
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=8008)
