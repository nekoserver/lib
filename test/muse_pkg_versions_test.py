import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'muse/pkg-versions.sh'


class MusePackageVersionsTest(unittest.TestCase):
    def test_reports_installed_and_repository_versions(self):
        with tempfile.TemporaryDirectory() as fixture:
            root = Path(fixture)
            binaries = {
                'nix-env': 'printf "tool-1.2   = 1.2\\ncustom-1.0   - ?\\n"',
                'dpkg-query': 'printf "ii \\tcurl\\t1:1.1-1\\nrc \\tremoved\\t8\\nii \\tlocal\\t2\\n"',
                'apt-cache': """cat <<'EOF'
curl:
  Installed: 1:1.1-1
  Candidate: 1:1.2-1
  Version table:
     1:1.2-1 500
        500 https://repo.example stable/main Packages
local:
  Installed: 2
  Candidate: 2
  Version table:
 *** 2 100
        100 /var/lib/dpkg/status
EOF""",
            }
            for name, body in binaries.items():
                path = root / name
                path.write_text('#!/bin/sh\n' + body + '\n')
                path.chmod(0o755)
            profile = root / '.nix-profile'
            profile.mkdir()
            (profile / 'manifest.json').write_text('{"elements":{"extra":{"storePaths":["/nix/store/hash-extra-0.9"]}}}')
            result = subprocess.run(
                ['sh', str(SCRIPT)], env={**os.environ, 'HOME': fixture, 'PATH': fixture + ':' + os.defpath},
                capture_output=True, text=True, timeout=10, check=True,
            )
        self.assertIn('tool\t1.2\t1.2', result.stdout)
        self.assertIn('custom\t1.0\t未確認', result.stdout)
        self.assertIn('extra\t0.9\t未確認', result.stdout)
        self.assertIn('curl\t1:1.1-1\t1:1.2-1', result.stdout)
        self.assertIn('local\t2\t未確認', result.stdout)
        self.assertNotIn('removed', result.stdout)


if __name__ == '__main__':
    unittest.main()
