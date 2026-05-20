/**
 * ============================================
 * Slide Controller（自写幻灯片控制器）
 * ============================================
 *
 * 替代 Reveal.js，~50 行 JS，精确可控。
 * 支持键盘、鼠标滚轮、触摸滑动、编程控制。
 *
 * API:
 *   SlideController.go(index)     跳转到第 index 页（0-based）
 *   SlideController.next()        下一页
 *   SlideController.prev()        上一页
 *   SlideController.current()     当前页码
 *   SlideController.total()       总页数
 *
 * HTML 结构要求：
 *   div.slide-container > div.slide.active + div.slide * N
 *
 * 动画元素标记：
 *   div.anim.anim-up.d2 （.anim + 方向 + 延迟）
 *   - .anim: 初始隐藏
 *   - .anim-up/.anim-left/...: 入场方向
 *   - .d1~.d12: 延迟时间
 *   - .show: 由控制器添加，触发入场
 *
 * 录制用自动翻页（在 page.evaluate 中调用）：
 *   SlideController.next() 按间隔调用即可
 */

(function () {
    "use strict";

    var slides = document.querySelectorAll(".slide");
    var total = slides.length;
    var current = 0;

    function go(index) {
        if (index < 0 || index >= total || index === current) return;

        // Exit current slide: 移除 active 和所有 .anim.show
        slides[current].classList.remove("active");
        slides[current].querySelectorAll(".anim").forEach(function (e) {
            e.classList.remove("show");
        });

        current = index;

        // Enter new slide: 添加 active，依次触发 .anim
        slides[current].classList.add("active");
        slides[current].querySelectorAll(".anim").forEach(function (e, i) {
            e.classList.remove("show");
            setTimeout(function () {
                e.classList.add("show");
            }, 150 + i * 250);
        });

        // 触发页面特定动画（如果已定义）
        if (typeof triggerSlideEffects === "function") {
            triggerSlideEffects(current);
        }
    }

    // 初始化第一页动画
    slides[0].querySelectorAll(".anim").forEach(function (e, i) {
        setTimeout(function () {
            e.classList.add("show");
        }, 300 + i * 250);
    });

    // 键盘控制
    document.addEventListener("keydown", function (e) {
        if (e.key === "ArrowRight" || e.key === "ArrowDown" || e.key === " ") {
            e.preventDefault();
            go(current + 1);
        } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
            e.preventDefault();
            go(current - 1);
        }
    });

    // 滚轮控制
    var wheelLock = false;
    document.addEventListener("wheel", function (e) {
        if (wheelLock) return;
        wheelLock = true;
        setTimeout(function () {
            wheelLock = false;
        }, 800);
        e.deltaY > 0 ? go(current + 1) : go(current - 1);
    });

    // 触摸滑动
    var touchStartX = 0;
    var touchStartY = 0;
    document.addEventListener("touchstart", function (e) {
        touchStartX = e.changedTouches[0].screenX;
        touchStartY = e.changedTouches[0].screenY;
    });
    document.addEventListener("touchend", function (e) {
        var dx = e.changedTouches[0].screenX - touchStartX;
        var dy = e.changedTouches[0].screenY - touchStartY;
        if (Math.abs(dx) > Math.abs(dy)) {
            dx < 0 ? go(current + 1) : go(current - 1);
        } else {
            dy < 0 ? go(current + 1) : go(current - 1);
        }
    });

    // 暴露 API
    window.SlideController = {
        go: go,
        next: function () {
            go(current + 1);
        },
        prev: function () {
            go(current - 1);
        },
        current: function () {
            return current;
        },
        total: function () {
            return total;
        },
    };
})();
