/**
 * ============================================
 * Slide Controller（教学动画控制器）
 * ============================================
 *
 * 功能：
 *   - 页面切换（键盘、滚轮、触摸）
 *   - CSS delay class 驱动的入场动画
 *   - data-step 分步揭示（按音频时长均分或精确时间轴）
 *   - slideTimelines 精确时间轴同步（trigger_at_sec）
 *   - slideTransitions 方向性页面转场
 *   - FLIP 布局动画（data-flip-id 元素在 step 切换时平滑移动）
 *   - SVG 描边动画（.svg-draw 元素跟随 .show 触发）
 *
 * HTML 结构要求：
 *   div.slide-container > div.slide.active + div.slide * N
 *
 * 动画元素标记：
 *   div.anim.anim-up.d2              — 入场动画 + CSS delay
 *   div.anim.anim-card.d3[data-step="1"]  — 分步揭示
 *   div.anim[data-anim-id="e2"]      — 时间轴精确控制
 *   div[data-flip-id="card1"]        — FLIP 布局动画
 *   path.svg-draw                    — SVG 描边动画
 *
 * 全局变量（由 pipeline 注入）：
 *   slideDurations: number[]      — 每页时长（毫秒）
 *   slideTimelines: array[]       — 每页时间轴 [{selector, at_ms}]
 *   slideTransitions: string[]    — 每页转场类型
 *
 * API:
 *   SlideController.go(index)
 *   SlideController.next()
 *   SlideController.prev()
 *   SlideController.current()
 *   SlideController.total()
 */

(function () {
    "use strict";

    var slides = document.querySelectorAll(".slide");
    var total = slides.length;
    var current = 0;
    var transitioning = false;
    var TRANSITION_DURATION = 500; // ms
    var DEFAULT_SLIDE_DURATION = 5000; // ms
    var FLIP_DURATION = 600; // ms

    // === 转场定义 ===
    var TRANSITIONS = {
        "push-left":  { exit: "slideExitLeft",    enter: "slideEnterRight" },
        "push-right": { exit: "slideExitRight",   enter: "slideEnterLeft" },
        "zoom":       { exit: "slideZoomOut",     enter: "slideZoomIn" },
        "dissolve":   { exit: "slideDissolveOut", enter: "slideDissolveIn" },
    };

    // === 工具函数 ===
    function getTransition(fromIndex, toIndex, direction) {
        var transitions = window.slideTransitions;
        if (!transitions || !transitions.length) return "push-left";

        var t = transitions[toIndex] || "push-left";

        if (direction === "backward") {
            if (t === "push-left") return "push-right";
            if (t === "push-right") return "push-left";
            if (t === "zoom") return "dissolve";
            if (t === "dissolve") return "zoom";
        }
        return t;
    }

    // === FLIP 工具 ===
    function captureFlipPositions(slide) {
        var positions = {};
        slide.querySelectorAll("[data-flip-id]").forEach(function (el) {
            var rect = el.getBoundingClientRect();
            positions[el.dataset.flipId] = { x: rect.left, y: rect.top, w: rect.width, h: rect.height };
        });
        return positions;
    }

    function animateFlip(slide, beforePositions) {
        slide.querySelectorAll("[data-flip-id]").forEach(function (el) {
            var id = el.dataset.flipId;
            var before = beforePositions[id];
            if (!before) return;

            var after = el.getBoundingClientRect();
            var dx = before.x - after.left;
            var dy = before.y - after.top;

            if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return;

            // Invert: 用 transform 将元素移回原位
            el.style.transform = "translate(" + dx + "px, " + dy + "px)";
            el.style.transition = "none";

            // Play: 下一帧移除 transform，触发 CSS transition
            requestAnimationFrame(function () {
                el.classList.add("flip-animating");
                el.style.transform = "";
                el.style.transition = "";

                setTimeout(function () {
                    el.classList.remove("flip-animating");
                }, FLIP_DURATION);
            });
        });
    }

    // === 退场 ===
    function exitSlide(index, transType) {
        var t = TRANSITIONS[transType] || TRANSITIONS["push-left"];
        var slide = slides[index];

        slide.classList.remove("active");
        slide.style.animationName = t.exit;
        slide.classList.add("transition-exit");

        slide.querySelectorAll(".anim").forEach(function (e) {
            e.classList.remove("show");
        });

        setTimeout(function () {
            slide.classList.remove("transition-exit");
            slide.style.animationName = "";
        }, TRANSITION_DURATION);
    }

    // === 入场 ===
    function enterSlide(index, transType) {
        var t = TRANSITIONS[transType] || TRANSITIONS["push-left"];
        var slide = slides[index];

        slide.style.animationName = t.enter;
        slide.classList.add("transition-enter", "active");

        setTimeout(function () {
            slide.classList.remove("transition-enter");
            slide.style.animationName = "";
        }, TRANSITION_DURATION);

        triggerAnimations(index);
    }

    // === 带 FLIP 的 step 触发 ===
    function showStepWithFlip(slide, step) {
        // First: 记录当前 FLIP 元素位置
        var beforePositions = captureFlipPositions(slide);

        // 触发该 step 的元素
        slide.querySelectorAll(".anim").forEach(function (e) {
            var s = parseInt(e.dataset.step || "0", 10);
            if (s === step && !e.dataset.animId) {
                e.classList.add("show");
            }
        });

        // Last + Invert + Play
        animateFlip(slide, beforePositions);
    }

    // === 动画触发核心逻辑 ===
    function triggerAnimations(index) {
        var slide = slides[index];
        var anims = slide.querySelectorAll(".anim");
        var timeline = window.slideTimelines && window.slideTimelines[index];
        var duration = (window.slideDurations && window.slideDurations[index]) || DEFAULT_SLIDE_DURATION;

        if (timeline && timeline.length > 0) {
            // 精确时间轴模式
            // 先处理不在时间轴管控内且没有 data-step 的元素：立即触发
            anims.forEach(function (e) {
                var animId = e.dataset.animId;
                var step = parseInt(e.dataset.step || "0", 10);
                if (!animId && step === 0) {
                    e.classList.add("show");
                }
            });

            // 注册时间轴触发
            timeline.forEach(function (entry) {
                setTimeout(function () {
                    var beforePositions = captureFlipPositions(slide);
                    var targets = slide.querySelectorAll(entry.selector);
                    targets.forEach(function (e) {
                        e.classList.add("show");
                    });
                    animateFlip(slide, beforePositions);
                }, entry.at_ms);
            });

            // data-step 元素按均分触发（带 FLIP）
            var maxStep = 0;
            anims.forEach(function (e) {
                var s = parseInt(e.dataset.step || "0", 10);
                if (s > maxStep) maxStep = s;
            });
            if (maxStep > 0) {
                var interval = duration / (maxStep + 1);
                for (var step = 1; step <= maxStep; step++) {
                    (function (s) {
                        setTimeout(function () {
                            showStepWithFlip(slide, s);
                        }, interval * s);
                    })(step);
                }
            }
        } else {
            // Fallback 模式：data-step 均分 或 全部立即触发
            var maxStep = 0;
            anims.forEach(function (e) {
                var s = parseInt(e.dataset.step || "0", 10);
                if (s > maxStep) maxStep = s;
            });

            var interval = maxStep > 0 ? duration / (maxStep + 1) : 0;

            // Step 0: 立即触发
            anims.forEach(function (e) {
                var step = parseInt(e.dataset.step || "0", 10);
                if (step === 0) {
                    e.classList.add("show");
                }
            });

            // Step 1+: 带 FLIP 延迟触发
            if (maxStep > 0) {
                for (var step = 1; step <= maxStep; step++) {
                    (function (s) {
                        setTimeout(function () {
                            showStepWithFlip(slide, s);
                        }, interval * s);
                    })(step);
                }
            }
        }

        // 触发页面特定动画（如果已定义）
        if (typeof triggerSlideEffects === "function") {
            triggerSlideEffects(index);
        }
    }

    // === 页面切换 ===
    function go(index) {
        if (index < 0 || index >= total || index === current || transitioning) return;
        transitioning = true;

        var direction = index > current ? "forward" : "backward";
        var transType = getTransition(current, index, direction);

        exitSlide(current, transType);

        setTimeout(function () {
            current = index;
            enterSlide(current, transType);
            transitioning = false;
        }, TRANSITION_DURATION);
    }

    // === 初始化第一页 ===
    triggerAnimations(0);

    // === 键盘控制 ===
    document.addEventListener("keydown", function (e) {
        if (e.key === "ArrowRight" || e.key === "ArrowDown" || e.key === " ") {
            e.preventDefault();
            go(current + 1);
        } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
            e.preventDefault();
            go(current - 1);
        }
    });

    // === 滚轮控制 ===
    var wheelLock = false;
    document.addEventListener("wheel", function (e) {
        if (wheelLock) return;
        wheelLock = true;
        setTimeout(function () {
            wheelLock = false;
        }, 600);
        e.deltaY > 0 ? go(current + 1) : go(current - 1);
    });

    // === 触摸滑动 ===
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

    // === 暴露 API ===
    window.SlideController = {
        go: go,
        next: function () { go(current + 1); },
        prev: function () { go(current - 1); },
        current: function () { return current; },
        total: function () { return total; },
    };
})();

// === scale-to-fit：内容超出 content-box 时，对 .fit-scale 整体等比缩小塞进框 ===
// 保留丰富内容、不裁切（reveal.js/Beamer 的做法）。缩放打在不被动画的 .fit-scale
// 内层，粒子/装饰在其外，互不干扰。见 docs/research/adaptive-slide-layout.md §4.3。
(function () {
    var MIN_SCALE = 0.62;  // 缩放下限，过小则可读性差，宁可极端页轻微裁切
    function fitAll() {
        // 对每一页都做 scale-to-fit：模板页缩 .fit-scale；自由发挥页（无 .fit-scale）
        // 缩 slide 的单一根容器。两者都"溢出才缩、不溢出不动"，避免内容被 overflow:hidden 裁切。
        var slides = document.querySelectorAll(".slide");
        for (var i = 0; i < slides.length; i++) {
            var slide = slides[i];
            var fs = slide.querySelector(".fit-scale") || slide.firstElementChild;
            if (!fs) continue;
            fs.style.transform = "";               // 复位后测自然高度
            fs.style.transformOrigin = "center";
            var box = fs.parentElement;            // 模板=.t2v-content-box；自由发挥=.slide
            if (!box) continue;
            var cs = getComputedStyle(box);
            var pad = (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0);
            var avail = box.clientHeight - pad;    // 扣掉容器自身上下 padding
            var natural = fs.offsetHeight;         // offsetHeight 不受 transform 影响
            if (avail > 0 && natural > avail + 2) {
                var s = Math.max(MIN_SCALE, avail / natural);
                fs.style.transform = "scale(" + s.toFixed(4) + ")";
            }
        }
    }
    if (document.fonts && document.fonts.ready) {
        document.fonts.ready.then(function () { setTimeout(fitAll, 30); });
    }
    window.addEventListener("load", function () { setTimeout(fitAll, 80); });
    window.addEventListener("resize", fitAll);
    window.__fitAll = fitAll;  // 便于测量脚本手动触发
})();
