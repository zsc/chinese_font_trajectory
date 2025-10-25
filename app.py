from flask import Flask, render_template, request, jsonify
# The 'json' import is not used, so it can be removed.
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
    # Find the maximum number of points in a segment (1 for M/L, 3 for C, 0 for Z)
    max_pts = 0
    for segment in path:
        # segment[0] is the command type, segment[1:] are the points
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
        
        # Pad with zeros to ensure all rows have the same length
        # 2 coordinates per point * (max points - current points)
        row.extend([0] * (2 * (max_pts - len(pts))))
        np_path.append(row)

    # Handle empty path case to avoid creating an empty array with incorrect dimensions
    if not np_path:
        # The number of features is 4 (one-hot) + 2 * max_pts
        num_features = 4 + 2 * max_pts
        return np.empty((0, num_features), dtype=np.float32)

    return np.array(np_path, dtype=np.float32)

def numpyToPath(np_path):
    """
    Converts a 2D numpy array back to a list of path commands.
    """
    path = []
    if np_path is None or np_path.shape[0] == 0:
        return path
        
    for row in np_path:
        # Find the most likely command by finding the index of the max value in the first 4 elements
        command_index = np.argmax(row[:4])
        
        if command_index == 0: # 'M'
            path.append(("M", (row[4], row[5])))
        elif command_index == 1: # 'L'
            path.append(("L", (row[4], row[5])))
        elif command_index == 2: # 'C'
            # Check if the array is wide enough for a curve
            if len(row) >= 10:
                path.append(("C", (row[4], row[5]), (row[6], row[7]), (row[8], row[9])))
        elif command_index == 3: # 'Z'
            path.append(("Z",))
    return path

def normalize_path(np_path):
    """
    Normalizes the coordinates in a numpy path array to the [0, 1] range.
    Returns the normalized path, offset, and scale factor.
    """
    # Handle empty or zero-row path
    if np_path.shape[0] == 0:
        return np_path, np.array([0., 0.]), 1.0

    coords = np_path[:, 4:]

    # Collect all valid coordinate values to find the bounding box, ignoring padding zeros
    all_x = []
    all_y = []
    for i in range(0, coords.shape[1], 2):
        x_col = coords[:, i]
        y_col = coords[:, i+1]
        # A point is considered to exist if it's not (0,0) padding
        mask = (x_col != 0) | (y_col != 0)
        all_x.extend(x_col[mask])
        all_y.extend(y_col[mask])

    if not all_x or not all_y:
        # This path has no coordinates (e.g., only 'Z' commands or is empty)
        return np_path, np.array([0., 0.]), 1.0

    min_x, max_x = min(all_x), max(all_x)
    min_y, max_y = min(all_y), max(all_y)

    offset = np.array([min_x, min_y])
    scale = max(max_x - min_x, max_y - min_y)

    if scale == 0:
        scale = 1.0  # Avoid division by zero for single-point paths

    normalized_path = np_path.copy()
    # Apply normalization to coordinate columns
    for i in range(4, normalized_path.shape[1], 2):
        x_col_idx, y_col_idx = i, i + 1
        
        # Create a mask for rows that have a point in this (x, y) slot.
        # This correctly handles points like (c, 0) or (0, c).
        point_exists_mask = (np_path[:, x_col_idx] != 0) | (np_path[:, y_col_idx] != 0)

        # Apply normalization only to the points that exist.
        normalized_path[point_exists_mask, x_col_idx] = (np_path[point_exists_mask, x_col_idx] - offset[0]) / scale
        normalized_path[point_exists_mask, y_col_idx] = (np_path[point_exists_mask, y_col_idx] - offset[1]) / scale

    return normalized_path, offset, scale


def denormalize_path(normalized_path, offset, scale):
    """Denormalizes a numpy path array using the given offset and scale."""
    denormalized_path = normalized_path.copy()
    # Apply the reverse transformation to all coordinate columns.
    for i in range(4, denormalized_path.shape[1], 2):
        denormalized_path[:, i] = denormalized_path[:, i] * scale + offset[0]
        denormalized_path[:, i+1] = denormalized_path[:, i+1] * scale + offset[1]
    return denormalized_path

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_trajectories', methods=['POST'])
def get_trajectories():
    data = request.get_json()
    text = data.get('text', '山居秋暝')
    font_path = '/System/Library/Fonts/STHeiti Medium.ttc' # Path for macOS, might need adjustment for other OS
    try:
        original_paths = get_glyph_paths(font_path, text)

        reconstructed_paths = {}
        for char, path in original_paths.items():
            # Convert path to numpy array
            np_path = pathToNumpy(path)

            # Normalize the path and store parameters for denormalization
            np_path_normalized, offset, scale = normalize_path(np_path)
            
            tokens = processor([np_path_normalized])
            
            # Since our batch size is 1, we take the first element [0].
            decoded_normalized_path = processor.decode(tokens)[0]

            # Denormalize the path to get back original coordinates
            decoded_path_np = denormalize_path(decoded_normalized_path, offset, scale)
            
            # Convert back to path command list
            reconstructed_paths[char] = numpyToPath(decoded_path_np)

        return jsonify({
            "original": original_paths,
            "reconstructed": reconstructed_paths
        })
    except FileNotFoundError:
        error_msg = f"Font file not found at {font_path}. Please update the path for your operating system."
        print(error_msg)
        return jsonify({"error": error_msg}), 500
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=8008)
