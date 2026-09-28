#define WIN32_LEAN_AND_MEAN
#define NOMINMAX

#include <windows.h>
#include <d3d11.h>
#include <dxgi1_2.h>
#include <dwmapi.h>
#include <fcntl.h>
#include <objidl.h>
#include <io.h>
#include <wincodec.h>
#include <wrl/client.h>

#include <winrt/base.h>
#include <winrt/Windows.Graphics.Capture.h>
#include <winrt/Windows.Graphics.DirectX.Direct3D11.h>
#include <windows.graphics.capture.interop.h>
#include <windows.graphics.directx.direct3d11.interop.h>

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <iostream>
#include <limits>
#include <string>
#include <stdexcept>
#include <vector>

#pragma comment(lib, "d3d11.lib")
#pragma comment(lib, "dxgi.lib")
#pragma comment(lib, "dwmapi.lib")
#pragma comment(lib, "ole32.lib")
#pragma comment(lib, "windowscodecs.lib")
#pragma comment(lib, "windowsapp.lib")

using Microsoft::WRL::ComPtr;
using namespace winrt;
using namespace winrt::Windows::Graphics::Capture;
using namespace winrt::Windows::Graphics::DirectX;
using namespace winrt::Windows::Graphics::DirectX::Direct3D11;

namespace {

constexpr int kUnavailable = 2;

struct Pixels {
    uint32_t width = 0;
    uint32_t height = 0;
    std::vector<uint8_t> bgra;
};

[[noreturn]] void unavailable(const std::string& message) {
    throw std::runtime_error(message);
}

void check_bool(BOOL value, const char* message) {
    if (!value) {
        unavailable(message);
    }
}

HWND parse_hwnd(int argc, wchar_t** argv) {
    for (int i = 1; i + 1 < argc; ++i) {
        if (std::wstring(argv[i]) == L"--hwnd") {
            try {
                auto value = std::stoull(argv[i + 1]);
                if (value == 0 || value > std::numeric_limits<uintptr_t>::max()) {
                    unavailable("无效的窗口句柄");
                }
                return reinterpret_cast<HWND>(static_cast<uintptr_t>(value));
            } catch (...) {
                unavailable("无效的窗口句柄");
            }
        }
    }
    unavailable("缺少 --hwnd 参数");
}

RECT client_bounds(HWND hwnd) {
    RECT client{};
    POINT origin{0, 0};
    check_bool(GetClientRect(hwnd, &client), "无法获取游戏客户区");
    check_bool(ClientToScreen(hwnd, &origin), "无法获取游戏客户区坐标");
    const LONG width = client.right - client.left;
    const LONG height = client.bottom - client.top;
    client.left = origin.x;
    client.top = origin.y;
    client.right = origin.x + width;
    client.bottom = origin.y + height;
    return client;
}

struct UnmapGuard {
    ID3D11DeviceContext* context;
    ID3D11Resource* resource;
    ~UnmapGuard() { context->Unmap(resource, 0); }
};

Pixels read_frame(HWND hwnd, const Direct3D11CaptureFrame& frame,
                  const ComPtr<ID3D11Device>& device,
                  const ComPtr<ID3D11DeviceContext>& context) {
    auto surface = frame.Surface();
    auto access = surface.as<::Windows::Graphics::DirectX::Direct3D11::IDirect3DDxgiInterfaceAccess>();
    ComPtr<ID3D11Texture2D> source;
    check_hresult(access->GetInterface(IID_PPV_ARGS(&source)));

    D3D11_TEXTURE2D_DESC source_desc{};
    source->GetDesc(&source_desc);
    if (source_desc.Width == 0 || source_desc.Height == 0 || source_desc.Width > 32000 || source_desc.Height > 32000) {
        unavailable("后台捕获尺寸无效");
    }

    D3D11_TEXTURE2D_DESC staging_desc = source_desc;
    staging_desc.Usage = D3D11_USAGE_STAGING;
    staging_desc.BindFlags = 0;
    staging_desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    staging_desc.MiscFlags = 0;
    ComPtr<ID3D11Texture2D> staging;
    check_hresult(device->CreateTexture2D(&staging_desc, nullptr, &staging));
    context->CopyResource(staging.Get(), source.Get());

    D3D11_MAPPED_SUBRESOURCE mapped{};
    check_hresult(context->Map(staging.Get(), 0, D3D11_MAP_READ, 0, &mapped));
    UnmapGuard unmap{context.Get(), staging.Get()};

    RECT client = client_bounds(hwnd);
    RECT window{};
    check_bool(GetWindowRect(hwnd, &window), "无法获取游戏窗口范围");
    RECT extended = window;
    DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, &extended, sizeof(extended));
    const LONG crop_width = client.right - client.left;
    const LONG crop_height = client.bottom - client.top;
    LONG crop_left = -1;
    LONG crop_top = -1;
    for (const RECT& bounds : {window, extended}) {
        const LONG candidate_left = client.left - bounds.left;
        const LONG candidate_top = client.top - bounds.top;
        if (candidate_left >= 0 && candidate_top >= 0 && crop_width > 0 && crop_height > 0 &&
            candidate_left + crop_width <= static_cast<LONG>(source_desc.Width) &&
            candidate_top + crop_height <= static_cast<LONG>(source_desc.Height)) {
            crop_left = candidate_left;
            crop_top = candidate_top;
            break;
        }
    }
    if (crop_left < 0 || crop_top < 0) {
        unavailable("后台捕获窗口范围与客户区不一致");
    }

    Pixels result;
    result.width = static_cast<uint32_t>(crop_width);
    result.height = static_cast<uint32_t>(crop_height);
    result.bgra.resize(static_cast<size_t>(result.width) * result.height * 4);
    const auto* base = static_cast<const uint8_t*>(mapped.pData);
    for (uint32_t row = 0; row < result.height; ++row) {
        const auto* source_row = base + static_cast<size_t>(crop_top + row) * mapped.RowPitch +
                                 static_cast<size_t>(crop_left) * 4;
        auto* target_row = result.bgra.data() + static_cast<size_t>(row) * result.width * 4;
        std::copy_n(source_row, static_cast<size_t>(result.width) * 4, target_row);
    }
    bool has_color = false;
    for (size_t offset = 0; offset < result.bgra.size(); offset += 4) {
        if (result.bgra[offset] || result.bgra[offset + 1] || result.bgra[offset + 2]) {
            has_color = true;
            break;
        }
    }
    if (!has_color) {
        unavailable("后台捕获返回全黑画面");
    }
    return result;
}

std::vector<uint8_t> encode_png(const Pixels& pixels) {
    ComPtr<IWICImagingFactory> factory;
    check_hresult(CoCreateInstance(CLSID_WICImagingFactory2, nullptr, CLSCTX_INPROC_SERVER,
                                   IID_PPV_ARGS(&factory)));
    ComPtr<IStream> stream;
    check_hresult(CreateStreamOnHGlobal(nullptr, TRUE, &stream));
    ComPtr<IWICBitmapEncoder> encoder;
    check_hresult(factory->CreateEncoder(GUID_ContainerFormatPng, nullptr, &encoder));
    check_hresult(encoder->Initialize(stream.Get(), WICBitmapEncoderNoCache));
    ComPtr<IWICBitmapFrameEncode> frame;
    ComPtr<IPropertyBag2> properties;
    check_hresult(encoder->CreateNewFrame(&frame, &properties));
    check_hresult(frame->Initialize(properties.Get()));
    check_hresult(frame->SetSize(pixels.width, pixels.height));
    WICPixelFormatGUID format = GUID_WICPixelFormat32bppBGRA;
    check_hresult(frame->SetPixelFormat(&format));
    check_hresult(frame->WritePixels(pixels.height, pixels.width * 4,
                                     static_cast<UINT>(pixels.bgra.size()),
                                     const_cast<BYTE*>(pixels.bgra.data())));
    check_hresult(frame->Commit());
    check_hresult(encoder->Commit());

    HGLOBAL handle = nullptr;
    check_hresult(GetHGlobalFromStream(stream.Get(), &handle));
    STATSTG status{};
    check_hresult(stream->Stat(&status, STATFLAG_NONAME));
    const ULONGLONG stream_size = status.cbSize.QuadPart;
    if (!stream_size || stream_size > std::numeric_limits<uint32_t>::max()) {
        unavailable("PNG 输出尺寸无效");
    }
    const auto* data = static_cast<const uint8_t*>(GlobalLock(handle));
    if (!data) {
        unavailable("无法读取 PNG 输出");
    }
    std::vector<uint8_t> output(data, data + static_cast<size_t>(stream_size));
    GlobalUnlock(handle);
    return output;
}

Pixels capture(HWND hwnd) {
    if (!IsWindow(hwnd) || !IsWindowVisible(hwnd) || IsIconic(hwnd)) {
        unavailable("游戏窗口不可进行后台捕获");
    }
    DWORD cloaked = 0;
    if (SUCCEEDED(DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, &cloaked, sizeof(cloaked))) && cloaked) {
        unavailable("游戏窗口被系统隐藏");
    }

    ComPtr<ID3D11Device> device;
    ComPtr<ID3D11DeviceContext> context;
    D3D_FEATURE_LEVEL feature_level{};
    const D3D_FEATURE_LEVEL levels[] = {D3D_FEATURE_LEVEL_11_1, D3D_FEATURE_LEVEL_11_0,
                                        D3D_FEATURE_LEVEL_10_1, D3D_FEATURE_LEVEL_10_0};
    check_hresult(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr,
                                    D3D11_CREATE_DEVICE_BGRA_SUPPORT, levels,
                                    ARRAYSIZE(levels), D3D11_SDK_VERSION, &device,
                                    &feature_level, &context));
    ComPtr<IDXGIDevice> dxgi_device;
    check_hresult(device.As(&dxgi_device));
    winrt::com_ptr<::IInspectable> inspectable;
    check_hresult(CreateDirect3D11DeviceFromDXGIDevice(dxgi_device.Get(), inspectable.put()));
    auto direct3d_device = inspectable.as<IDirect3DDevice>();

    GraphicsCaptureItem item{nullptr};
    auto interop = get_activation_factory<GraphicsCaptureItem, IGraphicsCaptureItemInterop>();
    check_hresult(interop->CreateForWindow(hwnd, guid_of<GraphicsCaptureItem>(),
                                            reinterpret_cast<void**>(put_abi(item))));
    auto pool = Direct3D11CaptureFramePool::CreateFreeThreaded(
        direct3d_device, DirectXPixelFormat::B8G8R8A8UIntNormalized, 1, item.Size());
    auto session = pool.CreateCaptureSession(item);
    session.IsCursorCaptureEnabled(false);
    session.StartCapture();

    Direct3D11CaptureFrame frame{nullptr};
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
    while (!frame && std::chrono::steady_clock::now() < deadline) {
        frame = pool.TryGetNextFrame();
        if (!frame) {
            Sleep(20);
        }
    }
    if (!frame) {
        unavailable("后台捕获未返回画面");
    }
    return read_frame(hwnd, frame, device, context);
}

}  // namespace

int wmain(int argc, wchar_t** argv) {
    try {
        init_apartment(apartment_type::multi_threaded);
        SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
        const HWND hwnd = parse_hwnd(argc, argv);
        const Pixels pixels = capture(hwnd);
        const auto png = encode_png(pixels);
        _setmode(_fileno(stdout), _O_BINARY);
        std::cout << "MCPYCAP1 " << pixels.width << ' ' << pixels.height << ' ' << png.size() << '\n';
        std::cout.write(reinterpret_cast<const char*>(png.data()), static_cast<std::streamsize>(png.size()));
        std::cout.flush();
        return 0;
    } catch (const winrt::hresult_error& error) {
        std::wcerr << error.message().c_str();
        return kUnavailable;
    } catch (const std::exception& error) {
        std::cerr << error.what();
        return kUnavailable;
    }
}
