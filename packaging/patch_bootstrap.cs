// A compact updater borrows only SHA-pinned files from the existing installation.
// The onedir engine starts inside a disposable, separately verified runtime.
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Text.RegularExpressions;
using Microsoft.Win32.SafeHandles;

internal static partial class PatchBootstrap
{
    private const string Reader = "ChaessiMetadataReader.exe";
    private const string Engine = "chaessi-update.exe";
    private const uint AccessRead = 0x80000000;
    private const uint AccessAttributes = 0x80;
    private const uint ReadControl = 0x00020000;
    private const uint ShareRead = 1;
    private const uint ShareWrite = 2;
    private const uint OpenExisting = 3;
    private const uint OpenReparsePoint = 0x00200000;
    private const uint BackupSemantics = 0x02000000;
    private const uint DirectoryAttribute = 0x10;
    private const uint ReparseAttribute = 0x400;

    [StructLayout(LayoutKind.Sequential)]
    private struct FileInfo
    {
        internal uint Attributes;
        internal System.Runtime.InteropServices.ComTypes.FILETIME Created, Accessed, Written;
        internal uint Volume, SizeHigh, SizeLow, Links, NumberHigh, NumberLow;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct SecurityAttributes
    {
        internal int Length;
        internal IntPtr Descriptor;
        internal int Inherit;
    }

    [DllImport("shell32.dll", ExactSpelling = true)]
    private static extern int SHGetKnownFolderPath(ref Guid id, uint flags, IntPtr token, out IntPtr path);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, ExactSpelling = true, SetLastError = true)]
    private static extern SafeFileHandle CreateFileW(string name, uint access, uint sharing, IntPtr security,
        uint disposition, uint flags, IntPtr template);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, ExactSpelling = true, SetLastError = true)]
    private static extern bool CreateDirectoryW(string path, ref SecurityAttributes security);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GetFileInformationByHandle(SafeFileHandle handle, out FileInfo information);

    [DllImport("advapi32.dll", ExactSpelling = true)]
    private static extern uint GetSecurityInfo(SafeFileHandle handle, int objectType, uint information,
        out IntPtr owner, out IntPtr group, out IntPtr dacl, out IntPtr sacl, out IntPtr descriptor);

    [DllImport("advapi32.dll", ExactSpelling = true)]
    private static extern uint GetSecurityDescriptorLength(IntPtr descriptor);

    [DllImport("kernel32.dll", ExactSpelling = true)]
    private static extern IntPtr LocalFree(IntPtr address);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, ExactSpelling = true)]
    private static extern uint GetDriveTypeW(string root);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, ExactSpelling = true, SetLastError = true)]
    private static extern uint GetWindowsDirectoryW(StringBuilder output, uint size);

    private static string KnownFolder(string id)
    {
        Guid guid = new Guid(id);
        IntPtr output;
        int status = SHGetKnownFolderPath(ref guid, 0, IntPtr.Zero, out output);
        try
        {
            if (status != 0 || output == IntPtr.Zero)
                throw new InvalidDataException("KNOWN_FOLDER_UNAVAILABLE");
            return LocalPath(Marshal.PtrToStringUni(output));
        }
        finally
        {
            if (output != IntPtr.Zero)
                Marshal.FreeCoTaskMem(output);
        }
    }

    private static string LocalPath(string path)
    {
        if (String.IsNullOrEmpty(path) || path.Length < 3 || path[1] != ':' || path[2] != '\\' ||
            !Char.IsLetter(path[0]) || path.IndexOf('/', 0) >= 0 ||
            !String.Equals(Path.GetFullPath(path), path, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("NON_LOCAL_PATH");
        string root = Path.GetPathRoot(path);
        if (GetDriveTypeW(root) != 3)
            throw new InvalidDataException("NON_FIXED_VOLUME");
        foreach (string part in path.Substring(root.Length).Split('\\'))
            if (part.EndsWith(" ", StringComparison.Ordinal) || part.EndsWith(".", StringComparison.Ordinal) ||
                part.IndexOf(':') >= 0)
                throw new InvalidDataException("NON_CANONICAL_PATH");
        return path;
    }

    private static SafeFileHandle OpenPinned(string path, bool directory, uint extraAccess = 0)
    {
        SafeFileHandle result = CreateFileW(path, (directory ? AccessAttributes : AccessRead) | extraAccess,
            directory ? ShareRead | ShareWrite : ShareRead, IntPtr.Zero, OpenExisting,
            OpenReparsePoint | (directory ? BackupSemantics : 0), IntPtr.Zero);
        if (result.IsInvalid)
        {
            int error = Marshal.GetLastWin32Error();
            result.Dispose();
            throw new Win32Exception(error);
        }
        FileInfo info;
        if (!GetFileInformationByHandle(result, out info))
        {
            int error = Marshal.GetLastWin32Error();
            result.Dispose();
            throw new Win32Exception(error);
        }
        if ((info.Attributes & ReparseAttribute) != 0 ||
            ((info.Attributes & DirectoryAttribute) != 0) != directory ||
            (!directory && info.Links != 1))
        {
            result.Dispose();
            throw new InvalidDataException("REPARSE_OR_HARD_LINK");
        }
        return result;
    }

    private static void CheckPrivateRoot(SafeFileHandle handle, RawSecurityDescriptor expected)
    {
        IntPtr owner, group, dacl, sacl, descriptor;
        uint status = GetSecurityInfo(handle, 1, 5, out owner, out group, out dacl, out sacl, out descriptor);
        try
        {
            if (status != 0 || descriptor == IntPtr.Zero)
                throw new Win32Exception((int)status);
            int length = checked((int)GetSecurityDescriptorLength(descriptor));
            byte[] data = new byte[length];
            Marshal.Copy(descriptor, data, 0, length);
            RawSecurityDescriptor actual = new RawSecurityDescriptor(data, 0);
            if (!expected.Owner.Equals(actual.Owner) ||
                (actual.ControlFlags & ControlFlags.DiscretionaryAclProtected) == 0 ||
                actual.DiscretionaryAcl == null ||
                actual.DiscretionaryAcl.BinaryLength != expected.DiscretionaryAcl.BinaryLength)
                throw new InvalidDataException("SCRATCH_ACL_REFUSED");
            byte[] observed = new byte[actual.DiscretionaryAcl.BinaryLength];
            byte[] wanted = new byte[expected.DiscretionaryAcl.BinaryLength];
            actual.DiscretionaryAcl.GetBinaryForm(observed, 0);
            expected.DiscretionaryAcl.GetBinaryForm(wanted, 0);
            for (int index = 0; index < wanted.Length; ++index)
                if (observed[index] != wanted[index])
                    throw new InvalidDataException("SCRATCH_ACL_REFUSED");
        }
        finally
        {
            if (descriptor != IntPtr.Zero)
                LocalFree(descriptor);
        }
    }

    private sealed class Pins : IDisposable
    {
        private readonly Dictionary<string, SafeFileHandle> directories =
            new Dictionary<string, SafeFileHandle>(StringComparer.OrdinalIgnoreCase);
        private readonly List<FileStream> files = new List<FileStream>();

        internal void Directory(string directory, RawSecurityDescriptor allowed = null)
        {
            if (directories.ContainsKey(directory))
                return;
            string parent = Path.GetDirectoryName(directory);
            if (parent != null)
                Directory(parent);
            SafeFileHandle handle = OpenPinned(directory, true, allowed == null ? 0 : ReadControl);
            try
            {
                if (allowed != null)
                    CheckPrivateRoot(handle, allowed);
                directories.Add(directory, handle);
            }
            catch { handle.Dispose(); throw; }
        }

        internal FileStream File(string path)
        {
            Directory(Path.GetDirectoryName(path));
            SafeFileHandle handle = OpenPinned(path, false);
            try { return new FileStream(handle, FileAccess.Read); }
            catch { handle.Dispose(); throw; }
        }

        internal void Capture(FileStream stream)
        {
            files.Add(stream);
        }

        internal void ReleaseFiles()
        {
            foreach (FileStream file in files)
                file.Dispose();
            files.Clear();
        }

        internal void ReleaseDirectory(string name)
        {
            SafeFileHandle directory;
            if (directories.TryGetValue(name, out directory))
            {
                directory.Dispose();
                directories.Remove(name);
            }
        }

        public void Dispose()
        {
            ReleaseFiles();
            foreach (SafeFileHandle directory in directories.Values)
                directory.Dispose();
            directories.Clear();
        }
    }

    private static bool ValidHash(string value)
    {
        return value != null && Regex.IsMatch(value, "^[0-9a-f]{64}\\z", RegexOptions.CultureInvariant);
    }

    private static string FilePath(string basePath, string relative)
    {
        if (relative == null || relative.Length > 230 || relative.IndexOf('\\') >= 0)
            throw new InvalidDataException("INVALID_BOOTSTRAP_PATH");
        string path = basePath;
        foreach (string part in relative.Split('/'))
        {
            string stem = part.Split('.')[0].TrimEnd(' ', '.');
            if (!Regex.IsMatch(part, "^[A-Za-z0-9_ .()+@,#=-]+\\z", RegexOptions.CultureInvariant) ||
                part.EndsWith(".", StringComparison.Ordinal) || part.EndsWith(" ", StringComparison.Ordinal) ||
                Regex.IsMatch(stem, "^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])\\z",
                    RegexOptions.IgnoreCase | RegexOptions.CultureInvariant))
                throw new InvalidDataException("INVALID_BOOTSTRAP_PATH");
            path = Path.Combine(path, part);
        }
        return path;
    }

    private static void ValidateTable(string[][] table, string root, bool reusable, HashSet<string> seen)
    {
        if (table == null || table.Length > 4096)
            throw new InvalidDataException("INVALID_BOOTSTRAP_MANIFEST");
        foreach (string[] entry in table)
        {
            if (entry == null || entry.Length != 2 || !ValidHash(entry[1]) ||
                (reusable && !entry[0].StartsWith("_internal/", StringComparison.Ordinal)) ||
                !seen.Add(FilePath(root, entry[0])))
                throw new InvalidDataException("INVALID_BOOTSTRAP_MANIFEST");
        }
    }

    private static string Digest(Stream stream)
    {
        using (SHA256 sha = SHA256.Create())
            return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
    }

    private static void Compare(FileStream stream, string expected)
    {
        string actual = Digest(stream);
        if (!String.Equals(actual, expected, StringComparison.Ordinal))
            throw new InvalidDataException("BOOTSTRAP_SHA256_MISMATCH");
        stream.Position = 0;
    }

    private sealed class Scratch : IDisposable
    {
        internal readonly string Root;
        internal readonly Pins Pinned = new Pins();
        private readonly List<string> files = new List<string>();
        private readonly List<string> directories = new List<string>();

        internal Scratch(string local)
        {
            Root = Path.Combine(local, "ChaessiPatchRuntime-" + Guid.NewGuid().ToString("N"));
            // The existing parent is held open throughout creation and use.
            // The random directory is trusted only after attesting its private DACL.
            Pinned.Directory(local);
            string sid;
            using (WindowsIdentity identity = WindowsIdentity.GetCurrent())
                sid = identity.User.Value;
            RawSecurityDescriptor acl = new RawSecurityDescriptor("O:" + sid + "D:P(A;OICI;FA;;;" + sid +
                ")(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)");
            try
            {
                byte[] descriptor = new byte[acl.BinaryLength];
                acl.GetBinaryForm(descriptor, 0);
                IntPtr buffer = Marshal.AllocHGlobal(descriptor.Length);
                try
                {
                    Marshal.Copy(descriptor, 0, buffer, descriptor.Length);
                    SecurityAttributes attributes = new SecurityAttributes();
                    attributes.Length = Marshal.SizeOf(typeof(SecurityAttributes));
                    attributes.Descriptor = buffer;
                    if (!CreateDirectoryW(Root, ref attributes))
                        throw new Win32Exception(Marshal.GetLastWin32Error());
                }
                finally
                {
                    Marshal.FreeHGlobal(buffer);
                }
                Pinned.Directory(Root, acl);
                directories.Add(Root);
            }
            catch
            {
                Dispose();
                throw;
            }
        }

        internal string Folder(string path)
        {
            string parent = Path.GetDirectoryName(path);
            if (!directories.Contains(path))
            {
                Folder(parent);
                if (Directory.Exists(path) || File.Exists(path))
                    throw new IOException("SCRATCH_COLLISION");
                Directory.CreateDirectory(path);
                directories.Add(path);
                Pinned.Directory(path);
            }
            return path;
        }

        internal void Copy(Pins source, string original, string destination, string expected)
        {
            Folder(Path.GetDirectoryName(destination));
            using (FileStream input = source.File(original))
            {
                Compare(input, expected);
                using (FileStream output = new FileStream(destination, FileMode.CreateNew, FileAccess.Write,
                    FileShare.None, 1024 * 1024, FileOptions.WriteThrough))
                {
                    files.Add(destination);
                    input.CopyTo(output, 1024 * 1024);
                    output.Flush(true);
                }
            }
            FileStream verified = Pinned.File(destination);
            try
            {
                Compare(verified, expected);
                Pinned.Capture(verified);
            }
            catch
            {
                verified.Dispose();
                throw;
            }
        }

        public void Dispose()
        {
            try
            {
                Pinned.ReleaseFiles();
                foreach (string file in files)
                    try { File.Delete(file); } catch (IOException) { } catch (UnauthorizedAccessException) { }
                for (int index = directories.Count - 1; index >= 0; --index)
                {
                    string name = directories[index];
                    Pinned.ReleaseDirectory(name);
                    try
                    {
                        if ((File.GetAttributes(name) & FileAttributes.ReparsePoint) == 0)
                            Directory.Delete(name, false);
                    }
                    catch (IOException) { } catch (UnauthorizedAccessException) { }
                }
            }
            finally { Pinned.Dispose(); }
        }
    }

    private static void Pump(object sender, DataReceivedEventArgs line)
    {
        if (line.Data != null)
            Console.WriteLine(line.Data);
    }

    private static int Run(string engine, string work, string payload, string local, string profile)
    {
        StringBuilder directory = new StringBuilder(32768);
        uint length = GetWindowsDirectoryW(directory, (uint)directory.Capacity);
        if (length == 0 || length >= directory.Capacity)
            throw new InvalidDataException("WINDOWS_DIRECTORY_UNAVAILABLE");
        string windows = LocalPath(directory.ToString());
        ProcessStartInfo start = new ProcessStartInfo(engine, "patch --payload \"" + payload + "\"");
        start.WorkingDirectory = work;
        start.UseShellExecute = false;
        start.CreateNoWindow = true;
        start.RedirectStandardOutput = true;
        start.RedirectStandardError = true;
        start.EnvironmentVariables.Clear();
        start.EnvironmentVariables.Add("SystemRoot", windows);
        start.EnvironmentVariables.Add("WINDIR", windows);
        start.EnvironmentVariables.Add("PATH", Path.Combine(windows, "System32"));
        start.EnvironmentVariables.Add("USERPROFILE", profile);
        start.EnvironmentVariables.Add("LOCALAPPDATA", local);
        start.EnvironmentVariables.Add("APPDATA", Path.Combine(profile, "AppData", "Roaming"));
        start.EnvironmentVariables.Add("TEMP", work);
        start.EnvironmentVariables.Add("TMP", work);
        start.EnvironmentVariables.Add("PYINSTALLER_RESET_ENVIRONMENT", "1");
        using (Process child = Process.Start(start))
        {
            if (child == null)
                throw new IOException("BOOTSTRAP_CHILD_NOT_STARTED");
            child.OutputDataReceived += Pump;
            child.ErrorDataReceived += Pump;
            child.BeginOutputReadLine();
            child.BeginErrorReadLine();
            child.WaitForExit();
            return child.ExitCode;
        }
    }

    private static int Execute()
    {
        if (!Environment.Is64BitProcess || !ValidHash(TargetExeHash))
            throw new InvalidDataException("INVALID_BOOTSTRAP_MANIFEST");
        string here = LocalPath(Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location));
        string local = KnownFolder("F1B32785-6FBA-4FCF-9D55-7B8E7F157091");
        string profile = KnownFolder("5E6C858F-0E22-4760-9AFE-EA3317B67173");
        if (!String.Equals(local, Path.Combine(profile, "AppData", "Local"), StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("UNSUPPORTED_PROFILE");
        string installed = Path.Combine(local, "Programs", "ChaessiMetadataReader");
        string staged = Path.Combine(here, "engine");
        string payload = Path.Combine(here, "payload");
        HashSet<string> seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        ValidateTable(StageFiles, staged, false, seen);
        ValidateTable(ReuseFiles, staged, true, seen);
        if (!seen.Contains(Path.Combine(staged, Engine)))
            throw new InvalidDataException("ENGINE_NOT_PINNED");

        using (Pins sources = new Pins())
        {
            sources.Directory(staged);
            sources.Directory(payload);
            sources.Directory(installed);
            using (Scratch map = new Scratch(local))
            {
                string runtime = Path.Combine(map.Root, "engine");
                string target = Path.Combine(map.Root, "payload");
                string work = map.Folder(Path.Combine(map.Root, "work"));
                foreach (string[] item in StageFiles)
                    map.Copy(sources, FilePath(staged, item[0]), FilePath(runtime, item[0]), item[1]);
                foreach (string[] item in ReuseFiles)
                    map.Copy(sources, FilePath(installed, item[0]), FilePath(runtime, item[0]), item[1]);
                map.Copy(sources, Path.Combine(payload, Reader), Path.Combine(target, Reader), TargetExeHash);
                return Run(Path.Combine(runtime, Engine), work, target, local, profile);
            }
        }
    }

    private static int Main(string[] arguments)
    {
        try
        {
            if (arguments.Length != 0)
                throw new InvalidDataException("BOOTSTRAP_ARGUMENTS_NOT_SUPPORTED");
            return Execute();
        }
        catch (Exception error)
        {
            // Avoid printing user paths or Windows app configuration.
            InvalidDataException reason = error as InvalidDataException;
            Console.Error.WriteLine(reason != null ? reason.Message : "BOOTSTRAP_WINDOWS_IO_REFUSED");
            return 2;
        }
    }
}
