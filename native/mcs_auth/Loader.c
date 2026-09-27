#include <windows.h>
#include <stdio.h>

/* CLR hosting only: no hooks, patches, or game operations. */
typedef HRESULT (WINAPI *CreateMeta)(const GUID*,const GUID*,void**);
typedef HRESULT (WINAPI *GetRuntime)(void*,LPCWSTR,const GUID*,void**);
typedef HRESULT (WINAPI *GetInterface)(void*,const GUID*,const GUID*,void**);
typedef HRESULT (WINAPI *StartRuntime)(void*);
typedef HRESULT (WINAPI *ExecuteManaged)(void*,LPCWSTR,LPCWSTR,LPCWSTR,LPCWSTR,DWORD*);
typedef ULONG (WINAPI *ReleaseObject)(void*);
static const GUID metaClsid={0x9280188d,0x0e8e,0x4867,{0xb3,0x0c,0x7f,0xa8,0x38,0x84,0xe8,0xde}};
static const GUID metaIid={0xd332db9e,0xb9b3,0x4125,{0x82,0x07,0xa1,0x48,0x84,0xf5,0x32,0x16}};
static const GUID infoIid={0xbd39d1d2,0xba2f,0x486a,{0x89,0xb0,0xb4,0xb0,0xcb,0x46,0x68,0x91}};
static const GUID hostClsid={0x90f1a06e,0x7712,0x4762,{0x86,0xb5,0x7a,0x5e,0xba,0x6b,0xdb,0x02}};
static const GUID hostIid={0x90f1a06c,0x7712,0x4762,{0x86,0xb5,0x7a,0x5e,0xba,0x6b,0xdb,0x02}};
#define METHOD(obj,index,type) ((type)(*(void***)(obj))[index])

static DWORD WINAPI Run(LPVOID module) {
    WCHAR dir[2048],dll[2048],status[2048];
    void *meta=NULL,*info=NULL,*host=NULL;
    HRESULT hr=E_FAIL;
    DWORD result=99,written;
    char message[100];
    HANDLE file;
    int i;
    if (!GetModuleFileNameW((HMODULE)module,dir,1900)) goto finish;
    for (i=lstrlenW(dir)-1;i>=0;i--) if (dir[i]=='\\') {dir[i]=0;break;}
    lstrcpyW(dll,dir);lstrcatW(dll,L"\\McpyMcsAuth.dll");
    lstrcpyW(status,dir);lstrcatW(status,L"\\loader-status.txt");
    {
        HMODULE clr=GetModuleHandleW(L"mscoree.dll");
        CreateMeta create=(CreateMeta)GetProcAddress(clr,"CLRCreateInstance");
        if (!create) goto report;
        hr=create(&metaClsid,&metaIid,&meta);
        if (FAILED(hr)) goto report;
        hr=METHOD(meta,3,GetRuntime)(meta,L"v4.0.30319",&infoIid,&info);
        if (FAILED(hr)) goto report;
        hr=METHOD(info,9,GetInterface)(info,&hostClsid,&hostIid,&host);
        if (FAILED(hr)) goto report;
        hr=METHOD(host,3,StartRuntime)(host);
        if (FAILED(hr)) goto report;
        hr=METHOD(host,11,ExecuteManaged)(host,dll,L"McpyMcsAuth.Entry",L"Capture",dir,&result);
    }
report:
    sprintf(message,"HRESULT=0x%08lx; managed_result=%lu",(unsigned long)hr,(unsigned long)result);
    file=CreateFileW(status,GENERIC_WRITE,FILE_SHARE_READ,NULL,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,NULL);
    if (file!=INVALID_HANDLE_VALUE) {WriteFile(file,message,lstrlenA(message),&written,NULL);CloseHandle(file);}
finish:
    if (host) METHOD(host,2,ReleaseObject)(host);
    if (info) METHOD(info,2,ReleaseObject)(info);
    if (meta) METHOD(meta,2,ReleaseObject)(meta);
    FreeLibraryAndExitThread((HMODULE)module,0);
    return 0;
}
BOOL WINAPI DllMain(HINSTANCE module,DWORD reason,LPVOID reserved) {
    if (reason==DLL_PROCESS_ATTACH) {
        HANDLE thread;
        DisableThreadLibraryCalls(module);
        thread=CreateThread(NULL,0,Run,module,0,NULL);
        if (thread) CloseHandle(thread);
    }
    return TRUE;
}
