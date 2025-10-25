document.addEventListener('DOMContentLoaded', () => {
    const textInput = document.getElementById('text-input');
    const visualizeBtn = document.getElementById('visualize-btn');
    const originalTrajectoriesDiv = document.getElementById('original-trajectories');

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
            displayTrajectories(data, originalTrajectoriesDiv);
        });
    });

    function displayTrajectories(trajectories, container) {
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
        ctx.translate(20, 180);
        ctx.scale(0.1, -0.1);
        ctx.beginPath();
        for (const segment of path) {
            const [type, ...pts] = segment;
            if (type === 'M') {
                ctx.moveTo(pts[0][0], pts[0][1]);
            } else if (type === 'L') {
                ctx.lineTo(pts[0][0], pts[0][1]);
            } else if (type === 'C') {
                ctx.bezierCurveTo(pts[0][0], pts[0][1], pts[1][0], pts[1][1], pts[2][0], pts[2][1]);
            } else if (type === 'Z') {
                ctx.closePath();
            }
        }
        ctx.stroke();
        ctx.restore();
    }
});