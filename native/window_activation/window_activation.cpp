// Process-scoped CBT hook installed on the owned game's suspended initial thread.
// No global hooks, foreground restoration, or changes to other applications.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <tlhelp32.h>

static HINSTANCE module_instance;

static LRESULT CALLBACK background_hook(int code, WPARAM wparam, LPARAM lparam) {
    if (code == HCBT_ACTIVATE || code == HCBT_SETFOCUS) return 1;
    if (code == HCBT_CREATEWND) {
        auto* created = reinterpret_cast<CBT_CREATEWNDW*>(lparam);
        if (!(created->lpcs->style & WS_CHILD)) {
            created->lpcs->dwExStyle |= WS_EX_NOACTIVATE;
            created->hwndInsertAfter = HWND_BOTTOM;
        }
    }
    return CallNextHookEx(nullptr, code, wparam, lparam);
}

extern "C" __declspec(dllexport) HHOOK McpyGuardInstall(DWORD pid, DWORD* thread_id) {
    HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
    if (snapshot == INVALID_HANDLE_VALUE) return nullptr;
    THREADENTRY32 entry{sizeof(entry)};
    DWORD initial = 0;
    if (Thread32First(snapshot, &entry)) {
        do {
            if (entry.th32OwnerProcessID == pid && (!*thread_id || *thread_id == entry.th32ThreadID)) {
                // Before first resume there must be exactly one initial thread.
                if (initial) {
                    CloseHandle(snapshot);
                    SetLastError(ERROR_INVALID_STATE);
                    return nullptr;
                }
                initial = entry.th32ThreadID;
            }
        } while (Thread32Next(snapshot, &entry));
    }
    CloseHandle(snapshot);
    if (!initial) { SetLastError(ERROR_NOT_FOUND); return nullptr; }
    *thread_id = initial;
    HHOOK hook = SetWindowsHookExW(WH_CBT, background_hook, module_instance, initial);
    return hook;
}

extern "C" __declspec(dllexport) BOOL McpyGuardResume(DWORD pid, DWORD thread_id) {
    HANDLE thread = OpenThread(THREAD_SUSPEND_RESUME | THREAD_QUERY_LIMITED_INFORMATION, FALSE, thread_id);
    if (!thread) return FALSE;
    if (GetProcessIdOfThread(thread) != pid) {
        CloseHandle(thread); SetLastError(ERROR_INVALID_PARAMETER); return FALSE;
    }
    DWORD previous = ResumeThread(thread);
    DWORD error = GetLastError();
    CloseHandle(thread);
    if (previous == static_cast<DWORD>(-1)) { SetLastError(error); return FALSE; }
    if (previous != 1) { SetLastError(ERROR_INVALID_STATE); return FALSE; }
    return TRUE;
}

extern "C" __declspec(dllexport) BOOL McpyGuardClose(HHOOK hook) {
    return UnhookWindowsHookEx(hook);
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) module_instance = instance;
    return TRUE;
}
