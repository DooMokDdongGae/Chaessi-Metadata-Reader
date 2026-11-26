"""Compile the compact bootstrap with an isolated test entry, never an installer."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest


BOOTSTRAP = Path(__file__).resolve().parents[1] / "patch_bootstrap.cs"
WINDOWS = Path(os.environ.get("SystemRoot", r"C:\Windows"))
CSC = WINDOWS / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"


STUB_CONFIG = """
internal static partial class PatchBootstrap {
    private static readonly string[][] StageFiles = new string[0][];
    private static readonly string[][] ReuseFiles = new string[0][];
    private const string TargetExeHash = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
}
"""


CHILD = """
using System;
using System.IO;
using System.Reflection;
internal static class EngineProbe {
    private static int Main(string[] args) {
        string half = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        if (args.Length != 3 || args[0] != "patch" || args[1] != "--payload")
            return 19;
        if (Environment.GetEnvironmentVariable("CHAESSI_BOOTSTRAP_PARENT_SENTINEL") != null)
            return 20;
        if (File.ReadAllText(Path.Combine(half, "_internal", "fixture.dll")) != "runtime" ||
                File.ReadAllText(Path.Combine(args[2], "ChaessiMetadataReader.exe")) != "fixture")
            return 21;
        return 17;
    }
}
"""


HARNESS = (
    r"""
using System;
using System.IO;

internal static class CompactBootstrapTest {
    private static int Main(string[] args) { return PatchBootstrap.Smoke(args); }
}
internal static partial class PatchBootstrap {
    internal static int Smoke(string[] args) {
        string basePath = args[0];
        string sourceEngine = Path.Combine(basePath, "fixture-engine.exe");
        string sourceRuntime = Path.Combine(basePath, "fixture-runtime");
        string sourcePayload = Path.Combine(basePath, "fixture-payload");
        string scratchPath;
        using (Pins source = new Pins())
        using (Scratch scratch = new Scratch(basePath)) {
            scratchPath = scratch.Root;
            string engine = Path.Combine(scratch.Root, "engine", "chaessi-update.exe");
            string payload = Path.Combine(scratch.Root, "payload");
            string work = scratch.Folder(Path.Combine(scratch.Root, "work"));
            try {
                scratch.Copy(source, sourcePayload, Path.Combine(payload, Reader), new string('a', 64));
                return 23;
            } catch (InvalidDataException reason) {
                if (reason.Message != "BOOTSTRAP_SHA256_MISMATCH")
                    return 24;
            }
            if (File.Exists(Path.Combine(payload, Reader)))
                return 25;
            scratch.Copy(source, sourceEngine, engine, args[1]);
            string runtime = Path.Combine(scratch.Root, "engine", "_internal", "fixture.dll");
            scratch.Copy(source, sourceRuntime, runtime, args[2]);
            scratch.Copy(source, sourcePayload, Path.Combine(payload, Reader), args[3]);
            try {
                using (File.Open(runtime, FileMode.Open, FileAccess.Write, FileShare.ReadWrite)) {}
                return 26;
            } catch (IOException) {}
            int code = Run(engine, work, payload, basePath, basePath);
            if (code != 17)
                return code;
        }
        if (Directory.Exists(scratchPath))
            return 27;
        return 0;
    }
}
"""
)


@unittest.skipUnless(os.name == "nt" and CSC.is_file(), "requires inbox x64 .NET Framework C# compiler")
class CompactBootstrapTests(unittest.TestCase):
    def test_native_copy_pin_hash_and_child_environment(self):
        import hashlib

        # Neither EXE is a Reader or installer. The harness can only form a
        # private scratch below the temporary directory passed to this test.
        with tempfile.TemporaryDirectory(prefix="chaessi-compact-bootstrap-test-") as temp:
            directory = Path(temp).resolve()
            root = Path(tempfile.gettempdir()).resolve()
            self.assertEqual(directory.parent, root)
            self.assertTrue(directory.name.startswith("chaessi-compact-bootstrap-test-"))
            child = directory / "fixture-engine.exe"
            harness = directory / "fixture-harness.exe"
            source = directory / "child.cs"
            source.write_text(CHILD, encoding="utf-8")
            common = [str(CSC), "/nologo", "/target:exe", "/platform:x64", "/optimize+", "/warnaserror+"]
            subprocess.run([*common, f"/out:{child}", str(source)], check=True, timeout=20)
            test_source = directory / "test.cs"
            config = directory / "config.cs"
            test_source.write_text(HARNESS, encoding="utf-8")
            config.write_text(STUB_CONFIG, encoding="utf-8")
            subprocess.run([*common, "/main:CompactBootstrapTest", f"/out:{harness}",
                            str(BOOTSTRAP), str(config), str(test_source)], check=True, timeout=20)
            runtime = directory / "fixture-runtime"
            runtime.write_bytes(b"runtime")
            target = directory / "fixture-payload"
            target.write_bytes(b"fixture")
            hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in (child, runtime, target)]
            env = dict(os.environ, CHAESSI_BOOTSTRAP_PARENT_SENTINEL="private ambient setting")
            result = subprocess.run([str(harness), str(directory), *hashes], capture_output=True,
                                    text=True, timeout=20, env=env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
