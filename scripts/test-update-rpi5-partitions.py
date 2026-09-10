#!/usr/bin/env python3
"""Non-destructive updater tests. Every disk/privilege/write command is mocked."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

MOCK = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
cmd = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['MOCK_LOG'], 'a') as log:
    log.write(json.dumps([cmd] + args) + '\n')
if cmd == 'diskutil' and args[0] == 'info':
    target = args[-1]
    if target == '/dev/disk999':
        print('Whole: Yes')
        print('Device Location: ' + ('Internal' if os.getenv('INTERNAL') else 'External'))
        size = 100 if os.getenv('BAD_SIZE') else 250059350016
        print(f'Disk Size: 250.1 GB ({size} Bytes)')
    else:
        index = int(target.split('s')[-1])
        geometry = [(1048576,134217728),(135266304,134217728),
                    (269484032,3221225472),(3490709504,3221225472),
                    (6711934976,402653184),(7114588160,402653184),
                    (7517241344,16777216),(7534018560,67108864),
                    (7601127424,242458205696)]
        offset, size = geometry[index-1]
        if os.getenv('BAD_LAYOUT') and index == 8: size = 242525314560
        print(f'Partition Offset: {offset} Bytes')
        print(f'Disk Size: 1.0 GB ({size} Bytes)')
elif cmd == 'sudo':
    if args == ['-v']: sys.exit(0)
    if args[:1] == ['-n']: args = args[1:]
    os.execvp(args[0], args)
elif cmd == 'dd':
    output = any(a.startswith('of=') for a in args)
    if output:
        sys.stdin.buffer.read()
        sys.exit(7 if os.getenv('FAIL_OUTPUT') else 0)
    if not any(a.startswith('if=') for a in args): sys.stdin.buffer.read()
    sys.stdout.buffer.write(b'mocked image data')
    sys.exit(6 if os.getenv('FAIL_INPUT') else 0)
elif cmd == 'gzip':
    sys.stdout.buffer.write(b'mocked gzip data')
    sys.exit(5 if os.getenv('FAIL_GZIP') else 0)
'''


class UpdaterTests(unittest.TestCase):
    def scenario(self, flags=(), compressed=False, **options):
        with tempfile.TemporaryDirectory(prefix="caramel-updater-test-") as temporary:
            root = Path(temporary)
            bindir = root / "bin"
            bindir.mkdir()
            for name in ("diskutil", "sudo", "dd", "gzip", "sync", "mke2fs"):
                script = bindir / name
                script.write_text(MOCK)
                script.chmod(0o755)
            image = root / ("fixture.img.gz" if compressed else "fixture.img")
            image.write_bytes(b"mock input, never a real image")
            log = root / "calls.jsonl"
            env = os.environ.copy()
            env.update(PATH=str(bindir) + os.pathsep + env["PATH"], MOCK_LOG=str(log))
            env.update({k: str(v) for k, v in options.items()})
            result = subprocess.run(["bash", str(Path(__file__).with_name("update-rpi5-partitions.sh")), *flags, str(image), "/dev/disk999"], env=env, capture_output=True, text=True)
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            writes = [call for call in calls if call[0] == "dd" and any(arg.startswith("of=") for arg in call)]
            formats = [call for call in calls if call[0] == "mke2fs"]
            return result, writes, formats

    def test_raw_and_gzip_preserve_data(self):
        for compressed in (False, True):
            result, writes, formats = self.scenario(compressed=compressed)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(writes), 6)
            for write in writes:
                self.assertIn("iflag=fullblock", write)
                self.assertIn("conv=notrunc", write)
            self.assertEqual([next(a for a in call if a.startswith("seek=")) for call in writes], ["seek=1", "seek=129", "seek=257", "seek=3329", "seek=6401", "seek=6785"])
            self.assertFalse(formats)

    def test_explicit_clean_formats_only_metadata_userdata(self):
        result, writes, formats = self.scenario(flags=("--clean-userdata",))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([call[-1] for call in formats], ["/dev/rdisk999s8", "/dev/rdisk999s9"])

    def test_reject_unsafe_or_old_targets_before_writes(self):
        for option in ("INTERNAL", "BAD_SIZE", "BAD_LAYOUT"):
            result, writes, formats = self.scenario(**{option: 1})
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(writes)
            self.assertFalse(formats)

    def test_pipeline_errors_are_not_lost(self):
        for option in ("FAIL_INPUT", "FAIL_OUTPUT", "FAIL_GZIP"):
            result, writes, formats = self.scenario(compressed=True, **{option: 1})
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(len(writes), 1)
            self.assertFalse(formats)


if __name__ == "__main__":
    unittest.main()
