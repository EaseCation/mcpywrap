// mcpy macOS 录制辅助程序：ScreenCaptureKit 窗口采集 + AVAssetWriter 恒定帧率 H.264 写盘。
// 命令行协议与 Windows mcpy-window-capture.exe 一致（--capabilities / --record / --extract），
// 区别只在于用 --pid 定位游戏窗口；source_time_100ns 为 mach 主机时钟（CLOCK_UPTIME_RAW）的 100ns 计数。
// 录制时游戏窗口保持在后台即可采集，不激活窗口、不移动光标、不发送任何输入。
// --input 是独立的前台设备输入模式：激活游戏后经 HID 事件流发送键鼠事件，与 Windows SendInput 后端语义一致。
import AVFoundation
import AppKit
import ApplicationServices
import CoreGraphics
import CoreMedia
import Foundation
import ImageIO
import ScreenCaptureKit
import UniformTypeIdentifiers
import VideoToolbox

let protocolVersion = 1
let maxPixels = 16_000_000
let maxBytes: UInt64 = 2 * 1024 * 1024 * 1024

func fail(_ message: String) -> Never {
    FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
    exit(1)
}

func emit(_ object: [String: Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]) else { return }
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data([10]))
}

func argument(_ name: String) -> String {
    let args = CommandLine.arguments
    guard let index = args.firstIndex(of: name), index + 1 < args.count else { fail("missing argument " + name) }
    return args[index + 1]
}

func hostSeconds() -> Double { CMTimeGetSeconds(CMClockGetTime(CMClockGetHostTimeClock())) }

func hasH264Encoder() -> Bool {
    var list: CFArray?
    guard VTCopyVideoEncoderList(nil, &list) == noErr, let encoders = list as? [[String: Any]] else { return false }
    return encoders.contains { ($0[kVTVideoEncoderList_CodecType as String] as? UInt32) == kCMVideoCodecType_H264 }
}

func capabilities() {
    var sck = false
    if #available(macOS 13.0, *) { sck = true }
    emit(["protocol": protocolVersion, "sck": sck, "h264_encoder": hasH264Encoder(),
          // AVFoundation 始终提供 H.264 软件解码；硬件可用性只作诊断。
          "h264_decoder": true, "h264_hardware_decoder": VTIsHardwareDecodeSupported(kCMVideoCodecType_H264),
          "screen_capture_permission": CGPreflightScreenCaptureAccess()])
}

/// 采集线程保留最近几帧及其源时间；写盘循环按输出时间轴挑选 PTS 最接近的一帧。
/// 只保留少量帧，避免长期占用 ScreenCaptureKit 的缓冲池（queueDepth）导致采集端丢帧。
final class FrameStore: NSObject, SCStreamOutput, SCStreamDelegate {
    static let keep = 5
    private let lock = NSLock()
    private var frames: [(CVPixelBuffer, Double)] = []
    private(set) var captured: UInt32 = 0
    private var lastAlive = hostSeconds()
    private var stopped = false
    private var lastSignature: UInt64 = 0

    func stream(_ stream: SCStream, didOutputSampleBuffer sample: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .screen, sample.isValid else { return }
        let info = (CMSampleBufferGetSampleAttachmentsArray(sample, createIfNecessary: false) as? [[SCStreamFrameInfo: Any]])?.first
        let status = (info?[.status] as? Int).flatMap(SCFrameStatus.init(rawValue:))
        lock.lock(); defer { lock.unlock() }
        // idle 表示画面没有变化但采集仍在进行；complete 但没有变化区域的重新合成也不算新的源画面。
        if status == .idle || status == .complete { lastAlive = hostSeconds() }
        guard status == .complete, let image = CMSampleBufferGetImageBuffer(sample) else { return }
        // 合成器可能重复提交内容未变的 complete 帧；用稀疏像素签名识别，不把它们计为新的源画面。
        let print = signature(image)
        if print == lastSignature, !frames.isEmpty { return }
        lastSignature = print
        frames.append((image, CMTimeGetSeconds(CMSampleBufferGetPresentationTimeStamp(sample))))
        if frames.count > FrameStore.keep { frames.removeFirst(frames.count - FrameStore.keep) }
        captured &+= 1
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        lock.lock(); stopped = true; lock.unlock()
    }

    var first: Double? { lock.lock(); defer { lock.unlock() }; return frames.first?.1 }

    /// 返回源时间最接近 target 的帧；缓存里都是更晚的帧时取最早的一帧。
    func nearest(_ target: Double) -> (CVPixelBuffer, Double)? {
        lock.lock(); defer { lock.unlock() }
        return frames.min(by: { abs($0.1 - target) < abs($1.1 - target) })
    }

    func health() -> (UInt32, Double, Bool) {
        lock.lock(); defer { lock.unlock() }
        return (captured, lastAlive, stopped)
    }
}

/// 128x128 网格采样的 FNV-1a 签名（约每 15 像素一个采样点），只用于识别内容未变的重复提交。
func signature(_ buffer: CVPixelBuffer) -> UInt64 {
    CVPixelBufferLockBaseAddress(buffer, .readOnly)
    defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
    guard let base = CVPixelBufferGetBaseAddress(buffer) else { return 0 }
    let width = CVPixelBufferGetWidth(buffer), height = CVPixelBufferGetHeight(buffer)
    let row = CVPixelBufferGetBytesPerRow(buffer)
    var hash: UInt64 = 0xcbf29ce484222325
    for y in 0..<128 {
        let line = base.advanced(by: (y * height / 128) * row)
        for x in 0..<128 {
            let pixel = line.load(fromByteOffset: (x * width / 128) * 4, as: UInt32.self)
            hash = (hash ^ UInt64(pixel)) &* 0x100000001b3
        }
    }
    return hash
}

/// 普通窗口的标题栏高度（点）；全屏窗口没有标题栏。与 Windows 客户区一致，录制和指针坐标都不含标题栏。
func titleInset(_ frame: CGRect) -> CGFloat {
    if NSScreen.screens.contains(where: { $0.frame.size == frame.size }) { return 0 }
    let style: NSWindow.StyleMask = [.titled, .closable, .miniaturizable, .resizable]
    return frame.height - NSWindow.contentRect(forFrameRect: NSRect(origin: .zero, size: frame.size), styleMask: style).height
}

enum WindowState { case ok, unavailable, resized }

func windowState(_ id: CGWindowID, size: CGSize) -> WindowState {
    guard let list = CGWindowListCopyWindowInfo([.optionIncludingWindow], id) as? [[String: Any]],
          let info = list.first,
          let bounds = info[kCGWindowBounds as String] as? [String: CGFloat] else { return .unavailable }
    // 最小化或关闭的窗口不再在屏幕上；被其他窗口遮挡时仍为 onscreen，可继续后台采集。
    if (info[kCGWindowIsOnscreen as String] as? Bool) != true { return .unavailable }
    if bounds["Width"] != size.width || bounds["Height"] != size.height { return .resized }
    return .ok
}

@available(macOS 13.0, *)
func record() async {
    guard let pid = pid_t(argument("--pid")), let fps = Int32(argument("--fps")),
          let duration = Int32(argument("--duration")) else { fail("invalid numeric argument") }
    let output = URL(fileURLWithPath: argument("--output"))
    let mapping = URL(fileURLWithPath: argument("--mapping"))
    let stop = argument("--stop-file")
    if !(1...60).contains(fps) || !(1...300).contains(duration) { fail("invalid duration/fps") }
    let files = FileManager.default
    if files.fileExists(atPath: output.path) || files.fileExists(atPath: mapping.path) { fail("output exists") }
    if !CGPreflightScreenCaptureAccess() { fail("screen_capture_permission_missing") }
    let content: SCShareableContent
    do {
        content = try await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: false)
    } catch {
        fail("screen capture content unavailable: \(error.localizedDescription)")
    }
    // 同一进程可能有菜单栏等辅助窗口；选取该进程最大的普通窗口作为游戏画面。
    guard let window = content.windows.filter({
        $0.owningApplication?.processID == pid && $0.windowLayer == 0
            && $0.frame.width >= 200 && $0.frame.height >= 200
    }).max(by: { $0.frame.width * $0.frame.height < $1.frame.width * $1.frame.height }) else {
        fail("game window not found for pid \(pid)")
    }
    let filter = SCContentFilter(desktopIndependentWindow: window)
    var scale = NSScreen.screens.first(where: { $0.frame.intersects(window.frame) })?.backingScaleFactor ?? 2
    if #available(macOS 14.0, *) { scale = CGFloat(filter.pointPixelScale) }
    let inset = titleInset(window.frame)
    let clientWidth = Int(window.frame.width * scale), clientHeight = Int((window.frame.height - inset) * scale)
    let width = (clientWidth + 1) & ~1, height = (clientHeight + 1) & ~1
    if width * height > maxPixels { fail("recording_resolution_limit") }
    let config = SCStreamConfiguration()
    config.sourceRect = CGRect(x: 0, y: inset, width: window.frame.width, height: window.frame.height - inset)
    config.width = width
    config.height = height
    // 120Hz 显示器上最小间隔取 1/60 会与刷新节拍错位而丢帧；取 1/120 可拿到游戏渲染的每一帧，
    // 恒定帧率输出由下面的写盘循环决定。
    config.minimumFrameInterval = CMTime(value: 1, timescale: 120)
    config.queueDepth = 8
    config.showsCursor = false
    config.pixelFormat = kCVPixelFormatType_32BGRA
    let store = FrameStore()
    let stream = SCStream(filter: filter, configuration: config, delegate: store)
    do {
        try stream.addStreamOutput(store, type: .screen, sampleHandlerQueue: DispatchQueue(label: "mcpy.capture"))
        try await stream.startCapture()
    } catch {
        fail("screen capture failed to start: \(error.localizedDescription)")
    }
    let deadline = hostSeconds() + 3
    while store.first == nil {
        if files.fileExists(atPath: stop) { emit(["event": "cancelled"]); try? await stream.stopCapture(); exit(0) }
        if hostSeconds() >= deadline { fail("no capture frame") }
        try? await Task.sleep(nanoseconds: 5_000_000)
    }
    let writer: AVAssetWriter
    do { writer = try AVAssetWriter(outputURL: output, fileType: .mp4) } catch { fail("writer: \(error.localizedDescription)") }
    let bitrate = min(max(width * height * Int(fps) / 6, 2_000_000), 60_000_000)
    let input = AVAssetWriterInput(mediaType: .video, outputSettings: [
        AVVideoCodecKey: AVVideoCodecType.h264, AVVideoWidthKey: width, AVVideoHeightKey: height,
        AVVideoCompressionPropertiesKey: [AVVideoAverageBitRateKey: bitrate,
                                          AVVideoMaxKeyFrameIntervalKey: Int(fps) * 2,
                                          AVVideoAllowFrameReorderingKey: false,
                                          AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel]])
    input.expectsMediaDataInRealTime = true
    let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: nil)
    guard writer.canAdd(input) else { fail("writer rejected H.264 input") }
    writer.add(input)
    guard writer.startWriting() else { fail("writer: \(writer.error?.localizedDescription ?? "start failed")") }
    writer.startSession(atSourceTime: .zero)
    files.createFile(atPath: mapping.path, contents: nil)
    guard let map = FileHandle(forWritingAtPath: mapping.path) else { fail("mapping not writable") }
    let size = window.frame.size
    // 输出第 k 帧对应源时间 origin + k/fps；写盘延后 lag 秒，等该时刻附近的源帧到达后再取最接近的一帧。
    // 源帧率与输出帧率相近时每个源帧恰好使用一次，不会因到达时刻与写盘节拍的相位差而重复/跳帧。
    let lag = 0.03
    let origin = store.first!
    var written: Int32 = 0, repeated: UInt32 = 0, used: UInt32 = 0
    var previous = -1.0
    var lastWindowCheck = 0.0
    var reason = "duration"
    while written < duration * fps {
        let now = hostSeconds()
        if files.fileExists(atPath: stop) { reason = "requested_stop"; break }
        let (_, alive, stopped) = store.health()
        if stopped { reason = "window_unavailable"; break }
        if now - lastWindowCheck > 0.1 {
            lastWindowCheck = now
            switch windowState(window.windowID, size: size) {
            case .unavailable: reason = "window_unavailable"
            case .resized: reason = "window_resized"
            case .ok: break
            }
            if reason != "duration" { break }
        }
        if now - alive > 3 { reason = "capture_stalled"; break }
        let target = origin + Double(written) / Double(fps)
        if now < target + lag { try? await Task.sleep(nanoseconds: 2_000_000); continue }
        if now - target - lag > 1 { fail("encoder_too_slow") }
        guard let (frame, pts) = store.nearest(target) else { fail("no capture frame") }
        if CVPixelBufferGetWidth(frame) != width || CVPixelBufferGetHeight(frame) != height { reason = "window_resized"; break }
        while !input.isReadyForMoreMediaData {
            if hostSeconds() - target - lag > 1 { fail("encoder_too_slow") }
            try? await Task.sleep(nanoseconds: 1_000_000)
        }
        if !adaptor.append(frame, withPresentationTime: CMTime(value: CMTimeValue(written), timescale: fps)) {
            fail("writer: \(writer.error?.localizedDescription ?? "append failed")")
        }
        let duplicate = previous == pts
        if duplicate { repeated += 1 } else { used += 1 }
        let line = String(format: "{\"frame\":%d,\"time\":%.12g,\"source_time_100ns\":%lld,\"repeated\":%@}\n",
                          written, Double(written) / Double(fps), Int64((pts * 1e7).rounded()), duplicate ? "true" : "false")
        map.write(line.data(using: .utf8)!)
        previous = pts
        written += 1
        if written == 1 {
            emit(["event": "ready", "width": width, "height": height, "client_width": clientWidth, "client_height": clientHeight])
        }
        if written % fps == 0 {
            if let attributes = try? files.attributesOfItem(atPath: output.path),
               let bytes = attributes[.size] as? UInt64, bytes > maxBytes { fail("video_size_limit") }
            emit(["event": "progress", "frames_written": written])
        }
    }
    try? await stream.stopCapture()
    if written == 0 { emit(["event": "cancelled"]); writer.cancelWriting(); exit(0) }
    if reason == "duration" {
        let end = origin + lag + Double(duration)
        while hostSeconds() < end && !files.fileExists(atPath: stop) { try? await Task.sleep(nanoseconds: 2_000_000) }
    }
    emit(["event": "finalizing"])
    try? map.close()
    input.markAsFinished()
    await writer.finishWriting()
    if writer.status != .completed { fail("writer: \(writer.error?.localizedDescription ?? "finalize failed")") }
    let captured = store.health().0
    emit(["event": "completed", "frames_written": written, "frames_captured": captured, "frames_repeated": repeated,
          "source_frames_skipped": captured &- used, "end_reason": reason])
}

func extract() {
    let input = URL(fileURLWithPath: argument("--input"))
    let output = URL(fileURLWithPath: argument("--output"))
    let requested = Set(argument("--frames").split(separator: ",").compactMap { Int64($0) })
    if requested.isEmpty || requested.count > 100 { fail("invalid frame selection") }
    let asset = AVURLAsset(url: input)
    guard let track = asset.tracks(withMediaType: .video).first else { fail("no video track") }
    let frameDuration = track.minFrameDuration
    guard frameDuration.isValid, frameDuration.value > 0 else { fail("invalid decoded frame rate") }
    let generator = AVAssetImageGenerator(asset: asset)
    generator.requestedTimeToleranceBefore = .zero
    generator.requestedTimeToleranceAfter = .zero
    var total: UInt64 = 0
    for index in requested.sorted() {
        let time = CMTimeMultiply(frameDuration, multiplier: Int32(index))
        var actual = CMTime.zero
        let image: CGImage
        do { image = try generator.copyCGImage(at: time, actualTime: &actual) } catch { fail("frame out of range") }
        // 写盘时间戳为 frame/fps，解码器必须回到同一帧，不允许就近替代。
        if CMTimeCompare(actual, time) != 0 { fail("decoder skipped requested frame") }
        let path = output.appendingPathComponent("frame-\(index).png")
        if FileManager.default.fileExists(atPath: path.path) { fail("frame output exists") }
        guard let destination = CGImageDestinationCreateWithURL(path as CFURL, UTType.png.identifier as CFString, 1, nil) else {
            fail("png writer unavailable")
        }
        CGImageDestinationAddImage(destination, image, nil)
        guard CGImageDestinationFinalize(destination) else { fail("png write failed") }
        total += (try? FileManager.default.attributesOfItem(atPath: path.path)[.size] as? UInt64) ?? 0
        if total > maxBytes { fail("frame_archive_size_limit") }
    }
}

func uptimeNanos() -> UInt64 { clock_gettime_nsec_np(CLOCK_UPTIME_RAW) }

/// 前台设备输入：stdin 每行一个 JSON 请求，stdout 每行一个响应；事件经 HID 事件流投递，需要“辅助功能”授权。
final class DeviceInput {
    let source = CGEventSource(stateID: .hidSystemState)
    var pid: pid_t = 0

    func window() -> (CGWindowID, CGRect)? {
        guard let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID)
                as? [[String: Any]] else { return nil }
        return list.compactMap { info -> (CGWindowID, CGRect)? in
            guard (info[kCGWindowOwnerPID as String] as? pid_t) == pid, (info[kCGWindowLayer as String] as? Int) == 0,
                  let id = info[kCGWindowNumber as String] as? CGWindowID,
                  let bounds = info[kCGWindowBounds as String] as? NSDictionary,
                  let rect = CGRect(dictionaryRepresentation: bounds), rect.width >= 200, rect.height >= 200 else { return nil }
            return (id, rect)
        }.max(by: { $0.1.width * $0.1.height < $1.1.width * $1.1.height })
    }

    /// 客户区：全局坐标（点，左上角原点）与像素尺寸。
    func client() -> (CGRect, CGFloat)? {
        guard let (_, frame) = window() else { return nil }
        let inset = titleInset(frame)
        let flipped = CGRect(x: frame.minX, y: NSScreen.screens.first!.frame.height - frame.maxY, width: frame.width, height: frame.height)
        let scale = NSScreen.screens.first(where: { $0.frame.intersects(flipped) })?.backingScaleFactor ?? 2
        return (CGRect(x: frame.minX, y: frame.minY + inset, width: frame.width, height: frame.height - inset), scale)
    }

    func frontmost() -> pid_t {
        // frontmostApplication 由主线程 run loop 上的系统通知更新；读取前先处理积压通知，避免拿到旧值。
        RunLoop.main.run(until: Date())
        return NSWorkspace.shared.frontmostApplication?.processIdentifier ?? -1
    }

    func ownerAt(_ point: CGPoint) -> pid_t {
        guard let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID)
                as? [[String: Any]] else { return -1 }
        for info in list where (info[kCGWindowLayer as String] as? Int) == 0 {
            if let bounds = info[kCGWindowBounds as String] as? NSDictionary,
               let rect = CGRect(dictionaryRepresentation: bounds), rect.contains(point) {
                return info[kCGWindowOwnerPID as String] as? pid_t ?? -1
            }
        }
        return -1
    }

    func state(_ keys: [Int]) -> [String: Any] {
        let cursor = CGEvent(source: nil)?.location ?? .zero
        var result: [String: Any] = ["frontmost": frontmost(), "post_allowed": CGPreflightPostEventAccess(),
                                     "buttons": [CGEventSource.buttonState(.hidSystemState, button: .left),
                                                 CGEventSource.buttonState(.hidSystemState, button: .right),
                                                 CGEventSource.buttonState(.hidSystemState, button: .center)],
                                     "keys_down": keys.filter { CGEventSource.keyState(.hidSystemState, key: CGKeyCode($0)) }]
        if let (rect, scale) = client() {
            result["client"] = ["x": rect.minX, "y": rect.minY, "width": Int(rect.width * scale),
                                "height": Int(rect.height * scale), "scale": scale]
            result["cursor"] = ["x": Int(((cursor.x - rect.minX) * scale).rounded(.down)),
                                "y": Int(((cursor.y - rect.minY) * scale).rounded(.down))]
            result["cursor_inside"] = rect.contains(cursor) && ownerAt(cursor) == pid
        }
        return result
    }

    func post(_ event: CGEvent?) throws -> [String: Any] {
        guard let event else { throw NSError(domain: "input", code: 1, userInfo: [NSLocalizedDescriptionKey: "event_unavailable"]) }
        let started = uptimeNanos()
        event.post(tap: .cghidEventTap)
        return ["send_started_ns": started, "send_finished_ns": uptimeNanos(), "accepted": true]
    }

    func handle(_ request: [String: Any]) throws -> [String: Any] {
        let op = request["op"] as? String ?? ""
        if op == "prepare" {
            guard let target = request["pid"] as? Int else { throw NSError(domain: "input", code: 2) }
            pid = pid_t(target)
            guard window() != nil, let app = NSRunningApplication(processIdentifier: pid) else {
                return ["ok": false, "code": "window_unavailable", "error": "game window not found"]
            }
            if frontmost() != pid {
                // macOS 14 起后台进程的 activate 请求会被协作式激活忽略；辅助功能授权下用 AX 设置前台并提升窗口。
                let element = AXUIElementCreateApplication(pid)
                AXUIElementSetAttributeValue(element, kAXFrontmostAttribute as CFString, kCFBooleanTrue)
                var windowRef: CFTypeRef?
                if AXUIElementCopyAttributeValue(element, kAXMainWindowAttribute as CFString, &windowRef) == .success,
                   let window = windowRef {
                    AXUIElementPerformAction(window as! AXUIElement, kAXRaiseAction as CFString)
                }
                if frontmost() != pid { app.activate(options: [.activateIgnoringOtherApps]) }
            }
            let deadline = Date().addingTimeInterval(1.5)
            while frontmost() != pid && Date() < deadline { RunLoop.main.run(until: Date().addingTimeInterval(0.01)) }
            return state(request["keys"] as? [Int] ?? []).merging(["ok": true]) { $1 }
        }
        if op == "state" { return state(request["keys"] as? [Int] ?? []).merging(["ok": true]) { $1 } }
        let down = request["down"] as? Bool ?? false
        // 释放事件始终投递，避免失去前台后在系统中残留按下状态；其余事件要求游戏仍在前台。
        let release = (op == "key" || op == "button") && !down
        guard pid != 0, release || frontmost() == pid else {
            return ["ok": false, "code": "foreground_lost", "error": "game is not frontmost"]
        }
        let cursor = CGEvent(source: nil)?.location ?? .zero
        switch op {
        case "key":
            guard let code = request["code"] as? Int else { throw NSError(domain: "input", code: 3) }
            return try post(CGEvent(keyboardEventSource: source, virtualKey: CGKeyCode(code), keyDown: down)).merging(["ok": true]) { $1 }
        case "button":
            let button = request["button"] as? String ?? "left"
            let (type, number): (CGEventType, CGMouseButton) = switch button {
            case "right": (down ? .rightMouseDown : .rightMouseUp, .right)
            case "middle": (down ? .otherMouseDown : .otherMouseUp, .center)
            default: (down ? .leftMouseDown : .leftMouseUp, .left)
            }
            return try post(CGEvent(mouseEventSource: source, mouseType: type, mouseCursorPosition: cursor,
                                    mouseButton: number)).merging(["ok": true]) { $1 }
        case "move", "relative":
            guard let (rect, scale) = client() else { return ["ok": false, "code": "window_unavailable", "error": "game window lost"] }
            var point = cursor
            if op == "move" {
                point = CGPoint(x: rect.minX + CGFloat(request["x"] as? Int ?? 0) / scale,
                                y: rect.minY + CGFloat(request["y"] as? Int ?? 0) / scale)
            } else {
                point.x += CGFloat(request["dx"] as? Int ?? 0) / scale
                point.y += CGFloat(request["dy"] as? Int ?? 0) / scale
            }
            // 按住按键时发送拖动事件，否则为普通移动；相对移动同时携带原始位移供锁定光标的游戏读取。
            let held: (CGEventType, CGMouseButton) =
                CGEventSource.buttonState(.hidSystemState, button: .left) ? (.leftMouseDragged, .left) :
                CGEventSource.buttonState(.hidSystemState, button: .right) ? (.rightMouseDragged, .right) : (.mouseMoved, .left)
            let event = CGEvent(mouseEventSource: source, mouseType: held.0, mouseCursorPosition: point, mouseButton: held.1)
            if op == "relative" {
                event?.setIntegerValueField(.mouseEventDeltaX, value: Int64(request["dx"] as? Int ?? 0))
                event?.setIntegerValueField(.mouseEventDeltaY, value: Int64(request["dy"] as? Int ?? 0))
            }
            return try post(event).merging(["ok": true]) { $1 }
        case "wheel":
            // Windows WHEEL_DELTA 为 120/格；macOS 以行为单位，正值向上。
            let delta = request["delta"] as? Int ?? 0
            let lines = delta == 0 ? 0 : (abs(delta) < 120 ? delta.signum() : delta / 120)
            return try post(CGEvent(scrollWheelEvent2Source: source, units: .line, wheelCount: 1,
                                    wheel1: Int32(lines), wheel2: 0, wheel3: 0)).merging(["ok": true]) { $1 }
        default:
            return ["ok": false, "code": "invalid_request", "error": "unknown op " + op]
        }
    }

    func run() {
        while let line = readLine(strippingNewline: true) {
            var reply: [String: Any]
            if let data = line.data(using: .utf8), let request = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                do { reply = try handle(request) } catch { reply = ["ok": false, "code": "invalid_request", "error": "\(error)"] }
                reply["id"] = request["id"]
            } else {
                reply = ["ok": false, "code": "invalid_request", "error": "invalid json"]
            }
            emit(reply)
        }
    }
}

@main
enum MacCapture {
    static func main() async {
        NSApplication.shared.setActivationPolicy(.prohibited)
        let args = CommandLine.arguments
        if args.contains("--capabilities") { capabilities(); return }
        if args.contains("--extract") { extract(); return }
        if args.contains("--input") { DeviceInput().run(); return }
        if args.contains("--record") {
            guard #available(macOS 13.0, *) else { fail("ScreenCaptureKit requires macOS 13") }
            await record()
            return
        }
        fail("usage: mcpy-macos-capture --capabilities | --record --pid P --fps N --duration S --output F --mapping F --stop-file F | --extract --input F --output D --frames a,b")
    }
}
