// Included in the capture translation unit to share client cropping and WIC encoding.

bool option(int argc, wchar_t** argv, const wchar_t* name) {
    for (int i = 1; i < argc; ++i) if (std::wstring(argv[i]) == name) return true;
    return false;
}

std::wstring argument(int argc, wchar_t** argv, const wchar_t* name) {
    for (int i = 1; i + 1 < argc; ++i) if (std::wstring(argv[i]) == name) return argv[i + 1];
    unavailable("missing video argument");
}

struct MediaLifetime {
    MediaLifetime() { check_hresult(MFStartup(MF_VERSION)); }
    ~MediaLifetime() { MFShutdown(); }
};

bool has_codec(const GUID& category, bool encoder) {
    MFT_REGISTER_TYPE_INFO type{MFMediaType_Video, MFVideoFormat_H264};
    IMFActivate** codecs = nullptr;
    UINT32 count = 0;
    const HRESULT hr = MFTEnumEx(category, MFT_ENUM_FLAG_SYNCMFT | MFT_ENUM_FLAG_LOCALMFT |
                                MFT_ENUM_FLAG_SORTANDFILTER, encoder ? nullptr : &type,
                                encoder ? &type : nullptr, &codecs, &count);
    for (UINT32 i = 0; i < count; ++i) codecs[i]->Release();
    CoTaskMemFree(codecs);
    return SUCCEEDED(hr) && count > 0;
}

int media_capabilities() {
    MediaLifetime media;
    std::cout << "{\"protocol\":1,\"wgc\":" << (GraphicsCaptureSession::IsSupported() ? "true" : "false")
              << ",\"h264_encoder\":" << (has_codec(MFT_CATEGORY_VIDEO_ENCODER, true) ? "true" : "false")
              << ",\"h264_decoder\":" << (has_codec(MFT_CATEGORY_VIDEO_DECODER, false) ? "true" : "false")
              << "}" << std::endl;
    return 0;
}

struct VideoWriter {
    ComPtr<IMFSinkWriter> writer;
    DWORD stream = 0;
    uint32_t width, height, fps;

    VideoWriter(const std::wstring& path, uint32_t w, uint32_t h, uint32_t rate)
        : width((w + 1) & ~1U), height((h + 1) & ~1U), fps(rate) {
        if (static_cast<uint64_t>(width) * height > 16000000) unavailable("recording_resolution_limit");
        try {
            initialize(path, true);
        } catch (const winrt::hresult_error&) {
            writer.Reset();
            std::filesystem::remove(path);
            initialize(path, false);
        }
    }

    void initialize(const std::wstring& path, bool hardware) {
        ComPtr<IMFAttributes> attributes;
        check_hresult(MFCreateAttributes(&attributes, 2));
        check_hresult(attributes->SetUINT32(MF_READWRITE_ENABLE_HARDWARE_TRANSFORMS, hardware));
        check_hresult(MFCreateSinkWriterFromURL(path.c_str(), nullptr, attributes.Get(), &writer));
        ComPtr<IMFMediaType> output, input;
        check_hresult(MFCreateMediaType(&output));
        check_hresult(output->SetGUID(MF_MT_MAJOR_TYPE, MFMediaType_Video));
        check_hresult(output->SetGUID(MF_MT_SUBTYPE, MFVideoFormat_H264));
        check_hresult(output->SetUINT32(MF_MT_AVG_BITRATE, 8000000));
        check_hresult(output->SetUINT32(MF_MT_INTERLACE_MODE, MFVideoInterlace_Progressive));
        check_hresult(MFSetAttributeSize(output.Get(), MF_MT_FRAME_SIZE, width, height));
        check_hresult(MFSetAttributeRatio(output.Get(), MF_MT_FRAME_RATE, fps, 1));
        check_hresult(MFSetAttributeRatio(output.Get(), MF_MT_PIXEL_ASPECT_RATIO, 1, 1));
        check_hresult(writer->AddStream(output.Get(), &stream));
        check_hresult(MFCreateMediaType(&input));
        check_hresult(input->SetGUID(MF_MT_MAJOR_TYPE, MFMediaType_Video));
        check_hresult(input->SetGUID(MF_MT_SUBTYPE, MFVideoFormat_RGB32));
        check_hresult(input->SetUINT32(MF_MT_INTERLACE_MODE, MFVideoInterlace_Progressive));
        check_hresult(input->SetUINT32(MF_MT_DEFAULT_STRIDE, width * 4));
        check_hresult(MFSetAttributeSize(input.Get(), MF_MT_FRAME_SIZE, width, height));
        check_hresult(MFSetAttributeRatio(input.Get(), MF_MT_FRAME_RATE, fps, 1));
        check_hresult(MFSetAttributeRatio(input.Get(), MF_MT_PIXEL_ASPECT_RATIO, 1, 1));
        check_hresult(writer->SetInputMediaType(stream, input.Get(), nullptr));
        ComPtr<ICodecAPI> codec;
        if (SUCCEEDED(writer->GetServiceForStream(stream, GUID_NULL, IID_PPV_ARGS(&codec)))) {
            VARIANT quality{};
            quality.vt = VT_UI4;
            quality.ulVal = 0;
            codec->SetValue(&CODECAPI_AVEncCommonQualityVsSpeed, &quality);
            quality.ulVal = fps * 2;
            codec->SetValue(&CODECAPI_AVEncMPVGOPSize, &quality);
        }
        check_hresult(writer->BeginWriting());
    }

    void write(const Pixels& pixels, uint32_t index) {
        ComPtr<IMFMediaBuffer> buffer;
        const DWORD bytes = width * height * 4;
        check_hresult(MFCreateMemoryBuffer(bytes, &buffer));
        BYTE* data = nullptr;
        check_hresult(buffer->Lock(&data, nullptr, nullptr));
        std::fill_n(data, bytes, 0);
        for (uint32_t row = 0; row < pixels.height; ++row) {
            std::copy_n(pixels.bgra.data() + static_cast<size_t>(row) * pixels.width * 4,
                        pixels.width * 4, data + static_cast<size_t>(row) * width * 4);
        }
        check_hresult(buffer->Unlock());
        check_hresult(buffer->SetCurrentLength(bytes));
        ComPtr<IMFSample> sample;
        check_hresult(MFCreateSample(&sample));
        check_hresult(sample->AddBuffer(buffer.Get()));
        const LONGLONG start = static_cast<LONGLONG>(index) * 10000000 / fps;
        const LONGLONG end = static_cast<LONGLONG>(index + 1) * 10000000 / fps;
        check_hresult(sample->SetSampleTime(start));
        check_hresult(sample->SetSampleDuration(end - start));
        check_hresult(writer->WriteSample(stream, sample.Get()));
    }
};

struct CaptureStream {
    ComPtr<ID3D11Device> device;
    ComPtr<ID3D11DeviceContext> context;
    ComPtr<ID3D11Texture2D> staging;
    GraphicsCaptureItem item{nullptr};
    Direct3D11CaptureFramePool pool{nullptr};
    GraphicsCaptureSession session{nullptr};
    HWND hwnd;
    DWORD pid = 0;

    explicit CaptureStream(HWND window) : hwnd(window) {
        GetWindowThreadProcessId(hwnd, &pid);
        check_hresult(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr,
            D3D11_CREATE_DEVICE_BGRA_SUPPORT, nullptr, 0, D3D11_SDK_VERSION, &device, nullptr, &context));
        ComPtr<IDXGIDevice> dxgi;
        check_hresult(device.As(&dxgi));
        winrt::com_ptr<::IInspectable> inspectable;
        check_hresult(CreateDirect3D11DeviceFromDXGIDevice(dxgi.Get(), inspectable.put()));
        auto interop = get_activation_factory<GraphicsCaptureItem, IGraphicsCaptureItemInterop>();
        check_hresult(interop->CreateForWindow(hwnd, guid_of<GraphicsCaptureItem>(),
                                              reinterpret_cast<void**>(put_abi(item))));
        pool = Direct3D11CaptureFramePool::CreateFreeThreaded(inspectable.as<IDirect3DDevice>(),
            DirectXPixelFormat::B8G8R8A8UIntNormalized, 3, item.Size());
        session = pool.CreateCaptureSession(item);
        session.IsCursorCaptureEnabled(false);
        session.StartCapture();
    }

    ~CaptureStream() {
        if (session) session.Close();
        if (pool) pool.Close();
    }

    bool next(Pixels& pixels, int64_t& timestamp, uint32_t& captured) {
        Direct3D11CaptureFrame latest{nullptr};
        for (int i = 0; i < 3; ++i) {
            auto frame = pool.TryGetNextFrame();
            if (!frame) break;
            latest = std::move(frame);
            ++captured;
        }
        if (!latest) return false;
        pixels = read_frame(hwnd, latest, device, context, false, &staging);
        timestamp = latest.SystemRelativeTime().count();
        return true;
    }

    bool valid() {
        DWORD current = 0, cloaked = 0;
        GetWindowThreadProcessId(hwnd, &current);
        DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, &cloaked, sizeof(cloaked));
        return current == pid && IsWindow(hwnd) && IsWindowVisible(hwnd) && !IsIconic(hwnd) && !cloaked;
    }
};

int record_video(int argc, wchar_t** argv) {
    const auto output = std::filesystem::path(argument(argc, argv, L"--output"));
    const auto mapping = std::filesystem::path(argument(argc, argv, L"--mapping"));
    const auto stop = std::filesystem::path(argument(argc, argv, L"--stop-file"));
    const int fps = std::stoi(argument(argc, argv, L"--fps"));
    const int duration = std::stoi(argument(argc, argv, L"--duration"));
    if (fps < 1 || fps > 60 || duration < 1 || duration > 300) unavailable("invalid duration/fps");
    if (std::filesystem::exists(output) || std::filesystem::exists(mapping)) unavailable("output exists");
    MediaLifetime media;
    CaptureStream capture(parse_hwnd(argc, argv));
    Pixels pixels;
    int64_t timestamp = 0;
    uint32_t captured = 0, written = 0, repeated = 0, used_sources = 0;
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
    while (!capture.next(pixels, timestamp, captured)) {
        if (std::filesystem::exists(stop)) { std::cout << "{\"event\":\"cancelled\"}" << std::endl; return 0; }
        if (std::chrono::steady_clock::now() >= deadline) unavailable("no capture frame");
        Sleep(5);
    }
    const auto client_width = pixels.width, client_height = pixels.height;
    VideoWriter writer(output.wstring(), client_width, client_height, fps);
    std::ofstream map(mapping);
    map.exceptions(std::ios::badbit | std::ios::failbit);
    int64_t previous = -1;
    auto last_frame = std::chrono::steady_clock::now();
    auto started = last_frame;
    std::string reason = "duration";
    while (written < static_cast<uint32_t>(duration * fps)) {
        const auto now = std::chrono::steady_clock::now();
        if (std::filesystem::exists(stop)) { reason = "requested_stop"; break; }
        if (!capture.valid()) { reason = "window_unavailable"; break; }
        RECT bounds = client_bounds(capture.hwnd);
        if (bounds.right - bounds.left != client_width || bounds.bottom - bounds.top != client_height) {
            reason = "window_resized"; break;
        }
        if (written && capture.next(pixels, timestamp, captured)) last_frame = now;
        if (now - last_frame > std::chrono::seconds(3)) { reason = "capture_stalled"; break; }
        const auto target = started + std::chrono::nanoseconds(static_cast<int64_t>(written) * 1000000000 / fps);
        if (now < target) { Sleep(2); continue; }
        if (now - target > std::chrono::seconds(1)) unavailable("encoder_too_slow");
        if (pixels.width != client_width || pixels.height != client_height) { reason = "window_resized"; break; }
        writer.write(pixels, written);
        const bool duplicate = previous == timestamp;
        if (duplicate) ++repeated; else ++used_sources;
        map << "{\"frame\":" << written << ",\"time\":" << std::setprecision(12)
            << static_cast<double>(written) / fps << ",\"source_time_100ns\":" << timestamp
            << ",\"repeated\":" << (duplicate ? "true" : "false") << "}\n";
        previous = timestamp;
        ++written;
        if (written == 1) {
            started = std::chrono::steady_clock::now();
            last_frame = started;
            std::cout << "{\"event\":\"ready\",\"width\":" << writer.width << ",\"height\":" << writer.height
                      << ",\"client_width\":" << client_width << ",\"client_height\":" << client_height << "}" << std::endl;
        }
        if (written % fps == 0) {
            map.flush();
            if (std::filesystem::file_size(output) > 2ULL * 1024 * 1024 * 1024) unavailable("video_size_limit");
            std::cout << "{\"event\":\"progress\",\"frames_written\":" << written << "}" << std::endl;
        }
    }
    if (!written) { std::cout << "{\"event\":\"cancelled\"}" << std::endl; return 0; }
    if (reason == "duration") {
        const auto end = started + std::chrono::seconds(duration);
        while (std::chrono::steady_clock::now() < end && !std::filesystem::exists(stop)) Sleep(2);
    }
    std::cout << "{\"event\":\"finalizing\"}" << std::endl;
    map.flush();
    check_hresult(writer.writer->Finalize());
    std::cout << "{\"event\":\"completed\",\"frames_written\":" << written << ",\"frames_captured\":" << captured
              << ",\"frames_repeated\":" << repeated << ",\"source_frames_skipped\":" << captured - used_sources
              << ",\"end_reason\":\"" << reason << "\"}" << std::endl;
    return 0;
}

int extract_frames(int argc, wchar_t** argv) {
    MediaLifetime media;
    const auto input = argument(argc, argv, L"--input");
    const auto output = std::filesystem::path(argument(argc, argv, L"--output"));
    std::set<uint32_t> requested;
    std::wistringstream selection(argument(argc, argv, L"--frames"));
    std::wstring token;
    while (std::getline(selection, token, L',')) requested.insert(std::stoul(token));
    if (requested.empty() || requested.size() > 100) unavailable("invalid frame selection");
    ComPtr<IMFAttributes> attributes;
    check_hresult(MFCreateAttributes(&attributes, 1));
    check_hresult(attributes->SetUINT32(MF_SOURCE_READER_ENABLE_VIDEO_PROCESSING, TRUE));
    ComPtr<IMFSourceReader> reader;
    check_hresult(MFCreateSourceReaderFromURL(input.c_str(), attributes.Get(), &reader));
    check_hresult(reader->SetStreamSelection(MF_SOURCE_READER_ALL_STREAMS, FALSE));
    check_hresult(reader->SetStreamSelection(MF_SOURCE_READER_FIRST_VIDEO_STREAM, TRUE));
    ComPtr<IMFMediaType> type;
    check_hresult(MFCreateMediaType(&type));
    check_hresult(type->SetGUID(MF_MT_MAJOR_TYPE, MFMediaType_Video));
    check_hresult(type->SetGUID(MF_MT_SUBTYPE, MFVideoFormat_RGB32));
    check_hresult(reader->SetCurrentMediaType(MF_SOURCE_READER_FIRST_VIDEO_STREAM, nullptr, type.Get()));
    check_hresult(reader->GetCurrentMediaType(MF_SOURCE_READER_FIRST_VIDEO_STREAM, &type));
    UINT32 width, height;
    check_hresult(MFGetAttributeSize(type.Get(), MF_MT_FRAME_SIZE, &width, &height));
    if (!width || !height || static_cast<uint64_t>(width) * height > 16000000) unavailable("invalid decoded dimensions");
    UINT32 numerator = 0, denominator = 0;
    check_hresult(MFGetAttributeRatio(type.Get(), MF_MT_FRAME_RATE, &numerator, &denominator));
    if (!numerator || !denominator) unavailable("invalid decoded frame rate");
    uint32_t index = 0;
    uint64_t total_bytes = 0;
    bool seek = *requested.begin() > 2 * numerator / denominator;
    while (!requested.empty()) {
        if (seek) {
            PROPVARIANT position{};
            position.vt = VT_I8;
            position.hVal.QuadPart = static_cast<int64_t>(*requested.begin()) * 10000000 * denominator / numerator;
            check_hresult(reader->SetCurrentPosition(GUID_NULL, position));
            seek = false;
        }
        ComPtr<IMFSample> sample;
        DWORD flags;
        LONGLONG time;
        check_hresult(reader->ReadSample(MF_SOURCE_READER_FIRST_VIDEO_STREAM, 0, nullptr, &flags, &time, &sample));
        if (flags & MF_SOURCE_READERF_ENDOFSTREAM) unavailable("frame out of range");
        if (!sample) continue;
        index = static_cast<uint32_t>((time * numerator + 5000000LL * denominator) / (10000000LL * denominator));
        if (index > *requested.begin()) unavailable("decoder skipped requested frame");
        const bool matched = requested.erase(index) != 0;
        if (matched) {
            // The decoder can renegotiate an aligned stride after the first ReadSample.
            check_hresult(reader->GetCurrentMediaType(MF_SOURCE_READER_FIRST_VIDEO_STREAM, &type));
            ComPtr<IMFMediaBuffer> buffer;
            check_hresult(sample->GetBufferByIndex(0, &buffer));
            ComPtr<IMF2DBuffer> two;
            BYTE* data = nullptr;
            LONG stride = width * 4;
            const bool is_two = SUCCEEDED(buffer.As(&two));
            if (is_two) check_hresult(two->Lock2D(&data, &stride));
            else {
                check_hresult(sample->ConvertToContiguousBuffer(&buffer));
                check_hresult(buffer->Lock(&data, nullptr, nullptr));
                UINT32 value = 0;
                if (SUCCEEDED(type->GetUINT32(MF_MT_DEFAULT_STRIDE, &value))) stride = static_cast<LONG>(value);
                if (stride < 0) data += static_cast<size_t>(height - 1) * -stride;
            }
            Pixels pixels{width, height, std::vector<uint8_t>(static_cast<size_t>(width) * height * 4)};
            for (uint32_t row = 0; row < height; ++row)
                std::copy_n(data + static_cast<ptrdiff_t>(row) * stride, width * 4,
                            pixels.bgra.data() + static_cast<size_t>(row) * width * 4);
            if (is_two) check_hresult(two->Unlock2D()); else check_hresult(buffer->Unlock());
            const auto png = encode_png(pixels);
            total_bytes += png.size();
            if (total_bytes > 2ULL * 1024 * 1024 * 1024) unavailable("frame_archive_size_limit");
            auto path = output / (L"frame-" + std::to_wstring(index) + L".png");
            if (std::filesystem::exists(path)) unavailable("frame output exists");
            std::ofstream file(path, std::ios::binary);
            file.exceptions(std::ios::badbit | std::ios::failbit);
            file.write(reinterpret_cast<const char*>(png.data()), png.size());
        }
        if (matched && !requested.empty() && *requested.begin() > index + 2 * numerator / denominator) seek = true;
    }
    return 0;
}
