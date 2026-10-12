import base64
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('register', Path(__file__).parents[1] / 'ops/ssh_key_register.py')
register = importlib.util.module_from_spec(spec)
spec.loader.exec_module(register)


def key(bits=3072):
    def field(value):
        return struct.pack('>I', len(value)) + value
    modulus = (1 << (bits-1)) | 1
    wire = field(b'ssh-rsa') + field(b'\x01\x00\x01') + field(b'\x00' + modulus.to_bytes(bits//8, 'big'))
    return 'ssh-rsa ' + base64.b64encode(wire).decode() + ' test', wire


class RegistrationTest(unittest.TestCase):
    def test_reject_options_truncation_extra_fields_and_weak_keys(self):
        valid, wire = key()
        bad = ['command="id" ' + valid, valid + '\n' + valid, key(2048)[0],
               'ssh-rsa ' + base64.b64encode(wire[:-1]).decode(),
               'ssh-rsa ' + base64.b64encode(wire+b'junk').decode()]
        for value in bad:
            with self.subTest(value=value[:40]), self.assertRaises(ValueError):
                register.validate(value)

    def test_preserve_existing_and_deduplicate(self):
        line, encoded, _ = register.validate(key()[0])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'authorized_keys'
            path.write_text('# existing\nssh-ed25519 old-key old-comment')
            self.assertTrue(register.append_key(path, line, encoded))
            first = path.read_text()
            self.assertTrue(first.startswith('# existing\nssh-ed25519 old-key old-comment\n'))
            self.assertFalse(register.append_key(path, line, encoded))
            self.assertEqual(path.read_text(), first)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            path.write_text('restrict ' + line + '\n')
            self.assertFalse(register.append_key(path, line, encoded))

    def test_reject_symlink_target(self):
        line, encoded, _ = register.validate(key()[0])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'link'
            path.symlink_to(Path(directory) / 'target')
            with self.assertRaises(OSError):
                register.append_key(path, line, encoded)


if __name__ == '__main__':
    unittest.main()
