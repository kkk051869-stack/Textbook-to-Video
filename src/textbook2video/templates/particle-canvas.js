/**
 * ============================================
 * Canvas Particle System（Canvas 粒子背景）
 * ============================================
 *
 * 轻量粒子系统，带连线效果。
 * 所有生成的动画 HTML 都可引入此脚本。
 *
 * 配色跟随 CSS 变量 --primary/--secondary/--accent 等。
 *
 * HTML 中需要：
 *   <canvas id="particleCanvas"></canvas>
 *
 * 参数可调：
 *   - count: 粒子数量（默认 80）
 *   - connectDist: 连线距离（默认 120px）
 *   - maxSpeed: 最大速度（默认 0.3）
 *   - alpha: 透明度范围 [0.06, 0.36]
 */

(function () {
    var canvas = document.getElementById("particleCanvas");
    if (!canvas) return;

    var ctx = canvas.getContext("2d");
    var particles = [];
    var count = 80;
    var connectDist = 120;

    function resize() {
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
    }
    resize();
    window.addEventListener("resize", resize);

    // 粒子颜色：跟随主题配色
    var colors = [
        [67, 97, 238],   // --primary: #4361ee
        [139, 92, 246],  // --secondary: #8b5cf6
        [249, 115, 22],  // --accent: #f97316
        [245, 158, 11],  // --gold: #f59e0b
        [100, 116, 139], // 灰色点缀
    ];

    function Particle() {
        this.reset();
    }

    Particle.prototype.reset = function () {
        this.x = Math.random() * canvas.width;
        this.y = Math.random() * canvas.height;
        this.size = Math.random() * 1.8 + 0.4;
        this.vx = (Math.random() - 0.5) * 0.3;
        this.vy = (Math.random() - 0.5) * 0.3;
        this.alpha = Math.random() * 0.3 + 0.06;
        var c = colors[Math.floor(Math.random() * colors.length)];
        this.r = c[0];
        this.g = c[1];
        this.b = c[2];
    };

    Particle.prototype.update = function () {
        this.x += this.vx;
        this.y += this.vy;
        if (this.x < 0 || this.x > canvas.width) this.reset();
        if (this.y < 0 || this.y > canvas.height) this.reset();
    };

    Particle.prototype.draw = function () {
        ctx.fillStyle =
            "rgba(" + this.r + "," + this.g + "," + this.b + "," + this.alpha + ")";
        ctx.beginPath();
        ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2);
        ctx.fill();
    };

    for (var i = 0; i < count; i++) particles.push(new Particle());

    function loop() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        for (var j = 0; j < particles.length; j++) {
            particles[j].update();
            particles[j].draw();
        }
        // 粒子连线
        for (var a = 0; a < particles.length; a++) {
            for (var b = a + 1; b < particles.length; b++) {
                var dx = particles[a].x - particles[b].x;
                var dy = particles[a].y - particles[b].y;
                var dist = Math.sqrt(dx * dx + dy * dy);
                if (dist < connectDist) {
                    ctx.strokeStyle =
                        "rgba(67,97,238," + (0.04 * (1 - dist / connectDist)) + ")";
                    ctx.lineWidth = 0.5;
                    ctx.beginPath();
                    ctx.moveTo(particles[a].x, particles[a].y);
                    ctx.lineTo(particles[b].x, particles[b].y);
                    ctx.stroke();
                }
            }
        }
        requestAnimationFrame(loop);
    }
    loop();
})();
