// mcpy-tracy-report：把 Tracy 0.11.1 采集文件汇总为 JSON，供 mcpy profile 与 AI Agent 读取。
// 输出区段（源码位置）统计与分位数、调用边、线程、帧标记，以及指定窗口区段最慢若干次内按线程的自身耗时归因。
#ifdef _WIN32
#  include <windows.h>
#endif

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

#include "../../server/TracyFileRead.hpp"
#include "../../server/TracyWorker.hpp"

namespace
{

constexpr size_t SampleCap = 65536;  // 每个区段保留的耗时样本上限（水塘抽样）

struct ZoneStat
{
    int16_t srcloc;
    int window = -1;  // 在窗口区段列表中的序号
    uint64_t count = 0;
    int64_t total = 0;  // 包含子区段；递归调用只计最外层
    int64_t self = 0;
    int64_t max = 0;
    int64_t min = INT64_MAX;
    uint32_t active = 0;  // 当前调用栈中的层数，用于递归去重
    std::unordered_map<uint64_t, int64_t> threadSelf;
    std::vector<int64_t> samples;
};

struct EdgeStat
{
    uint64_t count = 0;
    int64_t total = 0;
};

struct Instance
{
    int64_t duration;
    int64_t start;
    int64_t end;
    uint64_t thread;
};

struct Report
{
    tracy::Worker& worker;
    std::vector<std::string> windowNames;
    size_t slowest;
    std::vector<ZoneStat> zones;
    std::unordered_map<int16_t, size_t> index;
    std::unordered_map<uint64_t, EdgeStat> edges;  // (父索引+1)<<32 | 子索引
    std::unordered_map<uint64_t, int64_t> threadSelf;
    std::vector<std::vector<Instance>> windows;  // 每个窗口区段的最慢实例（小顶堆）
    uint64_t rng = 0x9e3779b97f4a7c15ull;

    Report( tracy::Worker& w, std::vector<std::string> names, size_t n )
        : worker( w ), windowNames( std::move( names ) ), slowest( n ), windows( windowNames.size() ) {}

    size_t Lookup( int16_t srcloc )
    {
        auto it = index.find( srcloc );
        if( it != index.end() ) return it->second;
        index.emplace( srcloc, zones.size() );
        zones.emplace_back();
        auto& stat = zones.back();
        stat.srcloc = srcloc;
        const char* name = worker.GetZoneName( worker.GetSourceLocation( srcloc ) );
        for( size_t i = 0; i < windowNames.size(); i++ )
        {
            if( windowNames[i] == name ) stat.window = (int)i;
        }
        return zones.size() - 1;
    }

    uint64_t Random()
    {
        rng ^= rng << 13; rng ^= rng >> 7; rng ^= rng << 17;
        return rng;
    }
};

bool Faster( const Instance& a, const Instance& b ) { return a.duration > b.duration; }

// 子区段容器可能是压缩存储（magic），统一按值遍历
template<typename F>
void ForEach( const tracy::Vector<tracy::short_ptr<tracy::ZoneEvent>>& vec, F&& f )
{
    if( vec.is_magic() )
    {
        auto& direct = *(const tracy::Vector<tracy::ZoneEvent>*)&vec;
        for( auto& zone : direct ) f( zone );
    }
    else
    {
        for( auto& zone : vec ) f( *zone );
    }
}

int64_t Visit( Report& r, const tracy::ZoneEvent& zone, int64_t parent, uint64_t tid )
{
    const int64_t start = zone.Start();
    const int64_t end = r.worker.GetZoneEnd( zone );
    const int64_t duration = std::max<int64_t>( 0, end - start );
    const size_t idx = r.Lookup( zone.SrcLoc() );
    const bool outermost = r.zones[idx].active == 0;
    r.zones[idx].active++;
    int64_t childTime = 0;
    if( zone.HasChildren() )
    {
        ForEach( r.worker.GetZoneChildren( zone.Child() ), [&]( const tracy::ZoneEvent& child ) {
            childTime += Visit( r, child, (int64_t)idx, tid );
        } );
    }
    r.zones[idx].active--;
    auto& stat = r.zones[idx];
    const int64_t self = std::max<int64_t>( 0, duration - childTime );
    stat.count++;
    if( outermost ) stat.total += duration;
    stat.self += self;
    stat.max = std::max( stat.max, duration );
    stat.min = std::min( stat.min, duration );
    stat.threadSelf[tid] += self;
    r.threadSelf[tid] += self;
    if( stat.samples.size() < SampleCap ) stat.samples.push_back( duration );
    else
    {
        const uint64_t j = r.Random() % stat.count;
        if( j < SampleCap ) stat.samples[j] = duration;
    }
    if( stat.window >= 0 && outermost && r.slowest )
    {
        auto& heap = r.windows[stat.window];
        if( heap.size() < r.slowest || duration > heap.front().duration )
        {
            if( heap.size() == r.slowest )
            {
                std::pop_heap( heap.begin(), heap.end(), Faster );
                heap.pop_back();
            }
            heap.push_back( { duration, start, end, tid } );
            std::push_heap( heap.begin(), heap.end(), Faster );
        }
    }
    auto& edge = r.edges[( (uint64_t)( parent + 1 ) << 32 ) | idx];
    edge.count++;
    edge.total += duration;
    return duration;
}

// 只统计落在 [begin, end) 内的部分；键为 线程序号<<32 | 区段索引
int64_t VisitClipped( Report& r, const tracy::ZoneEvent& zone, int64_t begin, int64_t end,
                      std::unordered_map<uint64_t, int64_t>& out, uint64_t threadSlot )
{
    const int64_t zs = std::max( zone.Start(), begin );
    const int64_t ze = std::min( r.worker.GetZoneEnd( zone ), end );
    if( ze <= zs ) return 0;
    int64_t childTime = 0;
    if( zone.HasChildren() )
    {
        ForEach( r.worker.GetZoneChildren( zone.Child() ), [&]( const tracy::ZoneEvent& child ) {
            if( child.Start() < end ) childTime += VisitClipped( r, child, begin, end, out, threadSlot );
        } );
    }
    out[( threadSlot << 32 ) | r.Lookup( zone.SrcLoc() )] += std::max<int64_t>( 0, ( ze - zs ) - childTime );
    return ze - zs;
}

void Escape( std::string& out, const char* s )
{
    out += '"';
    for( const unsigned char* p = (const unsigned char*)( s ? s : "" ); *p; ++p )
    {
        switch( *p )
        {
        case '"': out += "\\\""; break;
        case '\\': out += "\\\\"; break;
        case '\n': out += "\\n"; break;
        case '\r': out += "\\r"; break;
        case '\t': out += "\\t"; break;
        default:
            if( *p < 0x20 )
            {
                char buf[8];
                snprintf( buf, sizeof( buf ), "\\u%04x", *p );
                out += buf;
            }
            else out += (char)*p;
        }
    }
    out += '"';
}

void Key( std::string& out, const char* key )
{
    Escape( out, key );
    out += ':';
}

void Number( std::string& out, const char* key, int64_t value, bool comma = true )
{
    Key( out, key );
    out += std::to_string( value );
    if( comma ) out += ',';
}

void Text( std::string& out, const char* key, const char* value, bool comma = true )
{
    Key( out, key );
    Escape( out, value );
    if( comma ) out += ',';
}

int64_t Percentile( const std::vector<int64_t>& sorted, double p )
{
    if( sorted.empty() ) return 0;
    const size_t i = (size_t)( p * ( sorted.size() - 1 ) + 0.5 );
    return sorted[std::min( i, sorted.size() - 1 )];
}

void Distribution( std::string& out, std::vector<int64_t>& values )
{
    std::sort( values.begin(), values.end() );
    Number( out, "p50_ns", Percentile( values, 0.50 ) );
    Number( out, "p90_ns", Percentile( values, 0.90 ) );
    Number( out, "p95_ns", Percentile( values, 0.95 ) );
    Number( out, "p99_ns", Percentile( values, 0.99 ) );
}

void TopSelf( Report& r, std::string& out, int64_t begin, int64_t end )
{
    std::unordered_map<uint64_t, int64_t> inside;
    const auto& threads = r.worker.GetThreadData();
    for( size_t t = 0; t < threads.size(); t++ )
    {
        ForEach( threads[t]->timeline, [&]( const tracy::ZoneEvent& zone ) {
            if( zone.Start() < end ) VisitClipped( r, zone, begin, end, inside, t );
        } );
    }
    std::vector<std::pair<int64_t, uint64_t>> top;
    for( auto& kv : inside ) top.emplace_back( kv.second, kv.first );
    std::sort( top.begin(), top.end(), []( auto& a, auto& b ) { return a.first > b.first; } );
    if( top.size() > 16 ) top.resize( 16 );
    out += "\"top_self\":[";
    for( size_t k = 0; k < top.size(); k++ )
    {
        if( k ) out += ',';
        out += '{';
        Number( out, "zone", (int64_t)( top[k].second & 0xffffffff ) );
        Number( out, "thread", (int64_t)threads[top[k].second >> 32]->id );
        Number( out, "self_ns", top[k].first, false );
        out += '}';
    }
    out += ']';
}

int Usage( int code )
{
    fprintf( code ? stderr : stdout,
             "Usage: mcpy-tracy-report [--slowest N] [--window ZONE]... trace.tracy\n"
             "  --window  zone name whose slowest instances are attributed (default: \"Main Update\", serverUpdate)\n" );
    return code;
}

}

int main( int argc, char** argv )
{
#ifdef _WIN32
    SetConsoleOutputCP( CP_UTF8 );
#endif
    size_t slowest = 5;
    std::vector<std::string> windowNames;
    const char* path = nullptr;
    for( int i = 1; i < argc; i++ )
    {
        if( strcmp( argv[i], "--help" ) == 0 || strcmp( argv[i], "-h" ) == 0 ) return Usage( 0 );
        if( strcmp( argv[i], "--slowest" ) == 0 && i + 1 < argc ) slowest = (size_t)atoi( argv[++i] );
        else if( strcmp( argv[i], "--window" ) == 0 && i + 1 < argc ) windowNames.emplace_back( argv[++i] );
        else if( !path ) path = argv[i];
        else return Usage( 1 );
    }
    if( !path ) return Usage( 1 );
    if( windowNames.empty() ) windowNames = { "Main Update", "serverUpdate" };
    std::unique_ptr<tracy::FileRead> file( tracy::FileRead::Open( path ) );
    if( !file )
    {
        fprintf( stderr, "Cannot open trace file: %s\n", path );
        return 2;
    }
    tracy::Worker worker( *file );
    Report r( worker, windowNames, slowest );

    for( auto td : worker.GetThreadData() )
    {
        ForEach( td->timeline, [&]( const tracy::ZoneEvent& zone ) { Visit( r, zone, -1, td->id ); } );
    }

    // 帧标记：按需模式下首个标记可能早于连接，跳过不完整帧和最后一个未结束帧
    const int64_t first = worker.GetFirstTime();
    std::vector<int64_t> frames;
    const tracy::FrameData* fd = worker.GetFramesBase();
    if( fd && fd->continuous )
    {
        const size_t count = worker.GetFrameCount( *fd );
        for( size_t i = 1; i + 1 < count; i++ )
        {
            const int64_t t = worker.GetFrameTime( *fd, i );
            if( t > 0 && worker.GetFrameBegin( *fd, i ) >= first ) frames.push_back( t );
        }
    }

    std::string out;
    out.reserve( 1 << 20 );
    out += "{\"schema\":1,\"tool\":\"mcpy-tracy-report\",\"tracy_version\":\"0.11.1\",\"capture\":{";
    Text( out, "name", worker.GetCaptureName().c_str() );
    Text( out, "program", worker.GetCaptureProgram().c_str() );
    Number( out, "span_ns", worker.GetLastTime() - first );
    Number( out, "zone_count", (int64_t)worker.GetZoneCount(), false );
    out += "},\"frame_marks\":{";
    Number( out, "count", (int64_t)frames.size() );
    int64_t sum = 0;
    for( auto t : frames ) sum += t;
    Number( out, "mean_ns", frames.empty() ? 0 : sum / (int64_t)frames.size() );
    Distribution( out, frames );
    Number( out, "max_ns", frames.empty() ? 0 : frames.back(), false );
    out += "},\"windows\":[";
    for( size_t w = 0; w < windowNames.size(); w++ )
    {
        auto& heap = r.windows[w];
        std::sort( heap.begin(), heap.end(), Faster );
        if( w ) out += ',';
        out += '{';
        Text( out, "zone", windowNames[w].c_str() );
        out += "\"slowest\":[";
        for( size_t n = 0; n < heap.size(); n++ )
        {
            if( n ) out += ',';
            out += '{';
            Number( out, "start_ns", heap[n].start - first );
            Number( out, "duration_ns", heap[n].duration );
            Number( out, "thread", (int64_t)heap[n].thread );
            TopSelf( r, out, heap[n].start, heap[n].end );
            out += '}';
        }
        out += "]}";
    }
    out += "],\"threads\":[";
    bool comma = false;
    for( auto td : worker.GetThreadData() )
    {
        if( comma ) out += ',';
        comma = true;
        out += '{';
        Number( out, "id", (int64_t)td->id );
        Text( out, "name", worker.GetThreadName( td->id ) );
        Number( out, "self_ns", r.threadSelf[td->id], false );
        out += '}';
    }
    out += "],\"zones\":[";
    for( size_t i = 0; i < r.zones.size(); i++ )
    {
        auto& z = r.zones[i];
        const auto& srcloc = worker.GetSourceLocation( z.srcloc );
        if( i ) out += ',';
        out += '{';
        Text( out, "name", worker.GetZoneName( srcloc ) );
        Text( out, "function", worker.GetString( srcloc.function ) );
        Text( out, "file", worker.GetString( srcloc.file ) );
        Number( out, "line", srcloc.line );
        Number( out, "count", (int64_t)z.count );
        Number( out, "total_ns", z.total );
        Number( out, "self_ns", z.self );
        Number( out, "max_ns", z.max );
        Number( out, "min_ns", z.count ? z.min : 0 );
        Distribution( out, z.samples );
        out += "\"threads\":[";
        bool firstThread = true;
        for( auto& kv : z.threadSelf )
        {
            if( !firstThread ) out += ',';
            firstThread = false;
            out += '{';
            Number( out, "id", (int64_t)kv.first );
            Number( out, "self_ns", kv.second, false );
            out += '}';
        }
        out += "]}";
    }
    out += "],\"edges\":[";
    comma = false;
    for( auto& kv : r.edges )
    {
        if( comma ) out += ',';
        comma = true;
        out += '{';
        Number( out, "parent", (int64_t)( kv.first >> 32 ) - 1 );
        Number( out, "child", (int64_t)( kv.first & 0xffffffff ) );
        Number( out, "count", (int64_t)kv.second.count );
        Number( out, "total_ns", kv.second.total, false );
        out += '}';
    }
    out += "]}\n";
    fwrite( out.data(), 1, out.size(), stdout );
    return 0;
}
