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
 *
 * HTML 结构要求：
 *   div.slide-container > div.slide.active + div.slide * N
 *
 * 动画元素标记：
 *   div.anim.anim-up.d2              — 入场动画 + CSS delay
 *   div.anim.anim-card.d3[data-step="1"]  — 分步揭示
 *   div.anim[data-anim-id="e2"]      — 时间轴精确控制
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

        // 使用目标页的转场类型
        var t = transitions[toIndex] || "push-left";

        // 后退时反转方向
        if (direction === "backward") {
            if (t === "push-left") return "push-right";
            if (t === "push-right") return "push-left";
        }
        return t;
    }

    // === 退场 ===
    function exitSlide(index, transType) {
        var t = TRANSITIONS[transType] || TRANSITIONS["push-left"];
        var slide = slides[index];

        // 移除 active,触发退场动画
        slide.classList.remove("active");
        slide.style.animationName = t.exit;
        slide.classList.add("transition-exit");

        // 重置内部 anim 状态
        slide.querySelectorAll(".anim").forEach(function (e) {
            e.classList.remove("show");
        });

        // 退场动画结束后清理
        setTimeout(function () {
            slide.classList.remove("transition-exit");
            slide.style.animationName = "";
        }, TRANSITION_DURATION);
    }

    // === 入场 ===
    function enterSlide(index, transType) {
        var t = TRANSITIONS[transType] || TRANSITIONS["push-left"];
        var slide = slides[index];

        // 触发入场转场动画
        slide.style.animationName = t.enter;
        slide.classList.add("transition-enter", "active");

        // 入场转场结束后清理 class
        setTimeout(function () {
            slide.classList.remove("transition-enter");
            slide.style.animationName = "";
        }, TRANSITION_DURATION);

        // 触发内容动画
        triggerAnimations(index);
    }

    // === 动画触发核心逻辑 ===
    function triggerAnimations(index) {
        var slide = slides[index];
        var anims = slide.querySelectorAll(".anim");
        var timeline = window.slideTimelines && window.slideTimelines[index];

        if (timeline && timeline.length > 0) {
            // 精确时间轴模式：按 trigger_at_sec 触发指定元素
            timeline.forEach(function (entry) {
                setTimeout(function () {
                    var targets = slide.querySelectorAll(entry.selector);
                    targets.forEach(function (e) {
                        e.classList.add("show");
                    });
                }, entry.at_ms);
            });
            // 没有 data-step 也没有 data-anim-id 的元素：立即触发
            anims.forEach(function (e) {
                if (!e.dataset.step && !e.dataset.animId) {
                    e.classList.add("show");
                }
            });
        } else {
            // Fallback 模式：data-step 均分 或 全部立即触发
            var maxStep = 0;
            anims.forEach(function (e) {
                var s = parseInt(e.dataset.step || "0", 10);
                if (s > maxStep) maxStep = s;
            });

            var duration = (window.slideDurations && window.slideDurations[index]) || 5000;
            var interval = maxStep > 0 ? duration / (maxStep + 1) : 0;

            anims.forEach(function (e) {
                var step = parseInt(e.dataset.step || "0", 10);
                if (step === 0) {
                    e.classList.add("show");
                } else {
                    setTimeout(function () {
                        e.classList.add("show");
                    }, interval * step);
                }
            });
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

        // 退出当前页
        exitSlide(current, transType);

        // 进入新页（等退场动画完成）
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
        }, 800);
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
