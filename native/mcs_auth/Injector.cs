using System;
using System.Diagnostics;
using System.IO;
using System.IO.Pipes;
using System.Collections.Generic;
using System.Web.Script.Serialization;
using System.Runtime.InteropServices;
using System.Text;
using System.Reflection;

[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]
[assembly: AssemblyProduct("mcpywrap MCS identity bridge")]

class Injector {
    [DllImport("kernel32.dll",SetLastError=true)] static extern IntPtr OpenProcess(uint access,bool inherit,int pid);
    [DllImport("kernel32.dll",SetLastError=true)] static extern IntPtr VirtualAllocEx(IntPtr p,IntPtr a,UIntPtr size,uint type,uint protect);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool WriteProcessMemory(IntPtr p,IntPtr a,byte[] b,UIntPtr size,out UIntPtr written);
    [DllImport("kernel32.dll",SetLastError=true)] static extern IntPtr CreateRemoteThread(IntPtr p,IntPtr attr,UIntPtr stack,IntPtr start,IntPtr arg,uint flags,out uint tid);
    [DllImport("kernel32.dll",SetLastError=true)] static extern uint WaitForSingleObject(IntPtr h,uint ms);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool GetExitCodeThread(IntPtr h,out uint code);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool VirtualFreeEx(IntPtr p,IntPtr a,UIntPtr size,uint type);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode)] static extern IntPtr GetModuleHandle(string name);
    [DllImport("kernel32.dll",CharSet=CharSet.Ansi)] static extern IntPtr GetProcAddress(IntPtr module,string name);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool IsWow64Process(IntPtr p,out bool wow);

    static void Check(bool ok) {if (!ok) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());}
    static byte[] ReadExact(Stream stream,int count) {
        byte[] data=new byte[count];int offset=0;
        while(offset<count) {
            IAsyncResult pending=stream.BeginRead(data,offset,count-offset,null,null);
            if(!pending.AsyncWaitHandle.WaitOne(TimeSpan.FromSeconds(15)))throw new TimeoutException("Bridge response timeout");
            int n=stream.EndRead(pending);
            if(n==0)throw new EndOfStreamException();
            offset+=n;
        }
        return data;
    }
    static int Main(string[] args) {
        if (args.Length!=3) return 2;
        IntPtr process=IntPtr.Zero,buffer=IntPtr.Zero,thread=IntPtr.Zero;
        bool finished=false;
        try {
            var target=Process.GetProcessById(Int32.Parse(args[0]));
            string expected=Path.GetFullPath(args[1]);
            if (!String.Equals(target.MainModule.FileName,expected,StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("Target executable mismatch");
            if (target.ProcessName!="MCStudio") throw new InvalidOperationException("Unexpected process name");
            // Only rights required by the documented LoadLibrary injection path.
            process=OpenProcess(0x043A,false,target.Id);Check(process!=IntPtr.Zero);
            bool wow;Check(IsWow64Process(process,out wow));
            if (Environment.Is64BitOperatingSystem && !wow) throw new InvalidOperationException("Expected x86 target");
            byte[] path=Encoding.Unicode.GetBytes(Path.GetFullPath(args[2])+"\0");
            buffer=VirtualAllocEx(process,IntPtr.Zero,(UIntPtr)path.Length,0x3000,4);Check(buffer!=IntPtr.Zero);
            UIntPtr written;Check(WriteProcessMemory(process,buffer,path,(UIntPtr)path.Length,out written));
            Check(written.ToUInt64()==(ulong)path.Length);
            IntPtr localEntry=GetProcAddress(GetModuleHandle("kernel32.dll"),"LoadLibraryW");Check(localEntry!=IntPtr.Zero);
            IntPtr entry=IntPtr.Zero;
            foreach(ProcessModule local in Process.GetCurrentProcess().Modules) {
                long offset=localEntry.ToInt64()-local.BaseAddress.ToInt64();
                if(offset<0 || offset>=local.ModuleMemorySize)continue;
                foreach(ProcessModule remote in target.Modules)
                    if(String.Equals(local.FileName,remote.FileName,StringComparison.OrdinalIgnoreCase))
                        entry=new IntPtr(remote.BaseAddress.ToInt64()+offset);
                break;
            }
            if(entry==IntPtr.Zero)throw new InvalidOperationException("LoadLibrary module not found in target");
            uint tid;thread=CreateRemoteThread(process,IntPtr.Zero,UIntPtr.Zero,entry,buffer,0,out tid);Check(thread!=IntPtr.Zero);
            if (WaitForSingleObject(thread,15000)!=0) throw new TimeoutException("LoadLibrary did not finish");
            finished=true;
            uint code;Check(GetExitCodeThread(thread,out code));
            if (code==0) throw new InvalidOperationException("LoadLibrary failed");
            var json=new JavaScriptSerializer();
            var request=json.Deserialize<Dictionary<string,string>>(File.ReadAllText(Path.Combine(Path.GetDirectoryName(args[2]),"request.json")));
            using(var pipe=new NamedPipeClientStream(".",request["pipe"],PipeDirection.InOut,PipeOptions.Asynchronous)) {
                pipe.Connect(15000);
                byte[] nonce=Encoding.ASCII.GetBytes(request["nonce"]);
                pipe.Write(nonce,0,nonce.Length);pipe.Flush();
                int length=BitConverter.ToInt32(ReadExact(pipe,4),0);
                if(length<=0 || length>65536)throw new InvalidDataException("Bridge response size invalid");
                Console.OutputEncoding=new UTF8Encoding(false);
                Console.Write(Encoding.UTF8.GetString(ReadExact(pipe,length)));
            }
            return 0;
        } catch(Exception ex) {Console.Error.WriteLine(ex.GetType().Name+": "+ex.Message);return 1;}
        finally {
            if(thread!=IntPtr.Zero)CloseHandle(thread);
            if(buffer!=IntPtr.Zero && (finished || thread==IntPtr.Zero))VirtualFreeEx(process,buffer,UIntPtr.Zero,0x8000);
            if(process!=IntPtr.Zero)CloseHandle(process);
        }
    }
}
