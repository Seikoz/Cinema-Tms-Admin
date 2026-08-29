import importlib.util
import unittest
from pathlib import Path

from license_admin import contract


class ClientContractTest(unittest.TestCase):
    def test_sibling_client_uses_same_public_contract(self):
        client_module_path = Path(__file__).parents[2] / "Cinema_Tms" / "app" / "licensing.py"
        if not client_module_path.is_file():
            self.skipTest("Sibling Cinema_Tms client project is not available")
        spec = importlib.util.spec_from_file_location("cinema_tms_client_licensing", client_module_path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)

        self.assertEqual(contract.PRODUCT_ID, module.PRODUCT_ID)
        self.assertEqual(contract.LICENSE_SCHEMA, module.LICENSE_SCHEMA)
        self.assertEqual(contract.HARDWARE_REQUEST_SCHEMA, module.HARDWARE_REQUEST_SCHEMA)
        self.assertEqual(contract.TRUSTED_PUBLIC_KEY_PEM, module.TRUSTED_PUBLIC_KEY_PEM)
        self.assertEqual(contract.trusted_issuer_id(), module.trusted_issuer_id())


if __name__ == "__main__":
    unittest.main()
