#pragma once
#include <chrono>

// 原生调试时钟只返回经过时间；不按渲染帧、脚本 tick 或游戏时间计数。
namespace McpyInputClock {
inline double seconds() {
    using Clock = std::chrono::steady_clock;
    static_assert(Clock::is_steady, "Input clock must be monotonic");
    return std::chrono::duration<double>(Clock::now().time_since_epoch()).count();
}
}
