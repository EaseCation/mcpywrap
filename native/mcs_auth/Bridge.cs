using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Pipes;
using System.Reflection;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
using System.Web.Script.Serialization;

[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]
[assembly: AssemblyProduct("mcpywrap MCS identity bridge")]

namespace McpyMcsAuth {
    public static class Entry {
        const BindingFlags Static = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.FlattenHierarchy;
        const BindingFlags Instance = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;

        static object Manager(Assembly assembly, string name) {
            return assembly.GetType(name, true).GetProperty("Instance", Static).GetValue(null, null);
        }
        static object Property(object obj, string name) {
            return obj.GetType().GetProperty(name, Instance).GetValue(obj, null);
        }
        static Dictionary<string, object> Snapshot() {
            Assembly mcs = null;
            foreach (Assembly a in AppDomain.CurrentDomain.GetAssemblies())
                if (a.GetName().Name == "MCStudio") { mcs = a; break; }
            if (mcs == null) throw new InvalidOperationException("MCS assembly unavailable");
            Type core = mcs.GetType("MCStudio.Network.Http.CoreNative", true);
            string hex = (string)core.GetMethod("GetH5Token", Static).Invoke(null, null);
            if (String.IsNullOrEmpty(hex) || hex.Length % 2 != 0 || hex.Length > 4096)
                throw new InvalidOperationException("Invalid token shape");
            byte[] token = new byte[hex.Length / 2];
            for (int i = 0; i < token.Length; i++) token[i] = Convert.ToByte(hex.Substring(2*i, 2), 16);
            object user = Manager(mcs, "MCStudio.Modules.User.UserManager");
            object auth = Manager(mcs, "MCStudio.Modules.Auth.AuthManager");
            Type http = mcs.GetType("MCStudio.Network.Http.X19Http", true);
            return new Dictionary<string, object> {
                {"schema_version", 1},
                {"token", Convert.ToBase64String(token)},
                {"player_info", new Dictionary<string, object> {
                    {"user_id", Property(user,"PeUserId")},
                    {"user_name", Property(user,"Nickname")},
                    {"urs", Property(user,"Account")}
                }},
                {"auth_server_url", Property(auth,"AuthServerCppUrl")},
                {"web_server_url", http.GetField("WebServerUrl", Static).GetValue(null)},
                {"core_server_url", http.GetField("CoreServerUrl", Static).GetValue(null)},
                {"mcs_pid", Process.GetCurrentProcess().Id},
                {"captured_utc", DateTime.UtcNow.ToString("o")}
            };
        }
        public static int Capture(string directory) {
            string statusPath = Path.Combine(directory, "bridge-status.txt");
            try {
                var json = new JavaScriptSerializer();
                var request = json.Deserialize<Dictionary<string, string>>(File.ReadAllText(Path.Combine(directory,"request.json")));
                var security = new PipeSecurity();
                security.SetAccessRuleProtection(true,false);
                security.AddAccessRule(new PipeAccessRule(WindowsIdentity.GetCurrent().User, PipeAccessRights.FullControl, AccessControlType.Allow));
                using (var pipe = new NamedPipeServerStream(request["pipe"], PipeDirection.InOut, 1, PipeTransmissionMode.Byte,
                         PipeOptions.Asynchronous, 4096, 16384, security)) {
                    File.WriteAllText(statusPath,"waiting");
                    IAsyncResult pending = pipe.BeginWaitForConnection(null,null);
                    if (!pending.AsyncWaitHandle.WaitOne(TimeSpan.FromSeconds(20))) return 2;
                    pipe.EndWaitForConnection(pending);
                    byte[] expected = Encoding.ASCII.GetBytes(request["nonce"]);
                    byte[] actual = new byte[expected.Length];
                    int read = 0;
                    while (read < actual.Length) {
                        IAsyncResult input = pipe.BeginRead(actual, read, actual.Length-read, null, null);
                        if (!input.AsyncWaitHandle.WaitOne(TimeSpan.FromSeconds(5))) return 3;
                        int n = pipe.EndRead(input);
                        if (n == 0) return 3;
                        read += n;
                    }
                    if (Encoding.ASCII.GetString(actual) != request["nonce"]) return 4;
                    byte[] payload = Encoding.UTF8.GetBytes(json.Serialize(Snapshot()));
                    byte[] length = BitConverter.GetBytes(payload.Length);
                    pipe.Write(length,0,length.Length);
                    pipe.Write(payload,0,payload.Length);
                    pipe.Flush();
                }
                File.WriteAllText(statusPath,"complete");
                return 0;
            } catch (Exception ex) {
                // Never persist reflection exception messages or credential values.
                File.WriteAllText(statusPath,"error:"+ex.GetType().Name+
                    (ex.InnerException == null ? "" : ":"+ex.InnerException.GetType().Name));
                return 1;
            }
        }
    }
}
