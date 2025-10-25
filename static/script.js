document.addEventListener('DOMContentLoaded', () => {
    const textInput = document.getElementById('text-input');
    const visualizeBtn = document.getElementById('visualize-btn');
    const originalTrajectoriesDiv = document.getElementById('original-trajectories');
    const strokeWidthInput = document.getElementById('stroke-width');
    const scalingInput = document.getElementById('scaling');
    const colorGradientInput = document.getElementById('color-gradient');

    let trajectoriesData = null;

    visualizeBtn.addEventListener('click', () => {
        const text = textInput.value;
        fetch('/get_trajectories', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ text })
        })
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                alert('Error: ' + data.error);
                return;
            }
            trajectoriesData = data;
            displayTrajectories(trajectoriesData, originalTrajectoriesDiv);
        });
    });

    strokeWidthInput.addEventListener('input', () => displayTrajectories(trajectoriesData, originalTrajectoriesDiv));
    scalingInput.addEventListener('input', () => displayTrajectories(trajectoriesData, originalTrajectoriesDiv));
    colorGradientInput.addEventListener('change', () => displayTrajectories(trajectoriesData, originalTrajectoriesDiv));

    function displayTrajectories(trajectories, container) {
        if (!trajectories) return;
        container.innerHTML = '';
        for (const char in trajectories) {
            const path = trajectories[char];
            const canvas = document.createElement('canvas');
            canvas.width = 200;
            canvas.height = 200;
            canvas.classList.add('char-canvas');
            container.appendChild(canvas);
            const ctx = canvas.getContext('2d');
            drawPath(ctx, path);
        }
    }

    function drawPath(ctx, path) {
        ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
        ctx.save();
        const scale = parseFloat(scalingInput.value);
        ctx.translate(20, 180);
        ctx.scale(scale, -scale);
        ctx.lineWidth = parseFloat(strokeWidthInput.value) / scale;

        const useColorGradient = colorGradientInput.checked;
        let segmentIndex = 0;

        ctx.beginPath();
        for (const segment of path) {
            const [type, ...pts] = segment;

            if (useColorGradient) {
                const hue = (segmentIndex / path.length) * 360;
                ctx.strokeStyle = `hsl(${hue}, 100%, 50%)`;
            }

            if (type === 'M') {
                ctx.moveTo(pts[0][0], pts[0][1]);
            } else if (type === 'L') {
                ctx.lineTo(pts[0][0], pts[0][1]);
            } else if (type === 'C') {
                ctx.bezierCurveTo(pts[0][0], pts[0][1], pts[1][0], pts[1][1], pts[2][0], pts[2][1]);
            } else if (type === 'Z') {
                ctx.closePath();
            }

            if (useColorGradient) {
                ctx.stroke();
                ctx.beginPath();
                if (type !== 'Z') {
                    const lastPoint = pts[pts.length - 1];
                    ctx.moveTo(lastPoint[0], lastPoint[1]);
                }
            }
            segmentIndex++;
        }
        if (!useColorGradient) {
            ctx.stroke();
        }
        ctx.restore();
    }
});