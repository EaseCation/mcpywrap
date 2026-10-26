// 局域网自动加入使用 Windows 自带 OCR；坐标来自当前客户区画面。

std::string json_text(const std::string& text) {
    std::ostringstream out;
    out << '"';
    for (unsigned char ch : text) {
        if (ch == '"' || ch == '\\') out << '\\' << ch;
        else if (ch < 32) out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << static_cast<int>(ch) << std::dec;
        else out << ch;
    }
    out << '"';
    return out.str();
}

int ocr_pixels(const Pixels& pixels) {
    using namespace winrt::Windows::Graphics::Imaging;
    using namespace winrt::Windows::Media::Ocr;
    using namespace winrt::Windows::Storage::Streams;
    // 缩放到 OCR 上限以内，输出仍采用原客户区物理坐标。
    const double scale = std::min(1.0, static_cast<double>(OcrEngine::MaxImageDimension()) / std::max(pixels.width, pixels.height));
    const int width = static_cast<int>(pixels.width * scale);
    const int height = static_cast<int>(pixels.height * scale);
    std::vector<uint8_t> reduced(static_cast<size_t>(width) * height * 4);
    for (int y=0; y<height; ++y) for (int x=0; x<width; ++x) {
        size_t source = (static_cast<size_t>(y / scale) * pixels.width + static_cast<size_t>(x / scale)) * 4;
        std::copy_n(pixels.bgra.data()+source, 4, reduced.data()+(static_cast<size_t>(y)*width+x)*4);
    }
    DataWriter writer;
    writer.WriteBytes(reduced);
    SoftwareBitmap bitmap(BitmapPixelFormat::Bgra8, width, height, BitmapAlphaMode::Ignore);
    bitmap.CopyFromBuffer(writer.DetachBuffer());
    auto english = OcrEngine::TryCreateFromLanguage(winrt::Windows::Globalization::Language(L"en-US"));
    auto preferred = OcrEngine::TryCreateFromUserProfileLanguages();
    if (!english || !preferred) unavailable("Windows OCR language unavailable (English and display language required)");
    std::cout << "{\"protocol\":1,\"width\":" << pixels.width << ",\"height\":" << pixels.height
              << ",\"language\":" << json_text(to_string(preferred.RecognizerLanguage().LanguageTag())) << ",\"lines\":[";
    bool first = true;
    std::vector<OcrEngine> engines{english};
    if (english.RecognizerLanguage().LanguageTag()!=preferred.RecognizerLanguage().LanguageTag()) engines.push_back(preferred);
    for (auto const& engine : engines) {
    auto result = engine.RecognizeAsync(bitmap).get();
    for (auto const& line : result.Lines()) {
        double left=width, top=height, right=0, bottom=0;
        for (auto const& word : line.Words()) {
            auto box=word.BoundingRect();
            left=std::min(left, static_cast<double>(box.X)); top=std::min(top, static_cast<double>(box.Y));
            right=std::max(right, static_cast<double>(box.X+box.Width)); bottom=std::max(bottom, static_cast<double>(box.Y+box.Height));
        }
        if (!first) std::cout << ',';
        first=false;
        std::cout << "{\"text\":" << json_text(to_string(line.Text())) << ",\"bounds\":["
                  << left/scale << ',' << top/scale << ',' << right/scale << ',' << bottom/scale << "]}";
    }
    }
    std::cout << "]}" << std::endl;
    return 0;
}

int ocr_file(const std::wstring& path) {
    using namespace winrt::Windows::Storage;
    using namespace winrt::Windows::Storage::Streams;
    using namespace winrt::Windows::Graphics::Imaging;
    auto file=StorageFile::GetFileFromPathAsync(path).get();
    auto stream=file.OpenAsync(FileAccessMode::Read).get();
    auto decoder=BitmapDecoder::CreateAsync(stream).get();
    auto bitmap=decoder.GetSoftwareBitmapAsync(BitmapPixelFormat::Bgra8,BitmapAlphaMode::Ignore).get();
    Pixels pixels;
    pixels.width=bitmap.PixelWidth(); pixels.height=bitmap.PixelHeight();
    if (static_cast<uint64_t>(pixels.width)*pixels.height > 16000000) unavailable("ocr_resolution_limit");
    Buffer buffer(pixels.width*pixels.height*4);
    bitmap.CopyToBuffer(buffer);
    pixels.bgra.resize(buffer.Length());
    DataReader::FromBuffer(buffer).ReadBytes(pixels.bgra);
    return ocr_pixels(pixels);
}
