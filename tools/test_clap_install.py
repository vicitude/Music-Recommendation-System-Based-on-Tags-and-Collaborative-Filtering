import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import clap_install


class DownloadTests(unittest.TestCase):
    def test_verified_file_is_reused_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "weights"
            target.write_bytes(b"verified")
            with patch("clap_install.urllib.request.urlopen") as network:
                clap_install.download("https://example.invalid", target, hashlib.sha256(b"verified").hexdigest())
                network.assert_not_called()

    def test_existing_corrupt_file_is_not_loaded_or_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "weights"
            target.write_bytes(b"bad")
            with self.assertRaises(RuntimeError):
                clap_install.download("https://example.invalid", target, "0" * 64)
            self.assertEqual(target.read_bytes(), b"bad")

    def test_bad_download_never_becomes_final_weight(self):
        import io

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "weights"
            with patch("clap_install.urllib.request.urlopen", return_value=io.BytesIO(b"bad")):
                with self.assertRaises(RuntimeError):
                    clap_install.download("https://example.invalid", target, "0" * 64)
            self.assertFalse(target.exists())
            self.assertEqual(len(list(Path(directory).glob("temp_*.partial"))), 1)

    def test_download_hash_matches_before_final_rename(self):
        import io

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "weights"
            with patch("clap_install.urllib.request.urlopen", return_value=io.BytesIO(b"good")):
                clap_install.download("https://example.invalid", target, hashlib.sha256(b"good").hexdigest())
            self.assertEqual(target.read_bytes(), b"good")
            self.assertEqual(list(Path(directory).glob("*.partial")), [])


if __name__ == "__main__":
    unittest.main()
