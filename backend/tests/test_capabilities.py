"""Capabilities report active opt-ins without performing an evaluation."""

import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from lunarwindow.api.app import create_app
from lunarwindow.api.custom_runtime import CustomRuntime, CustomSettings


class CapabilitiesTests(unittest.TestCase):
    def test_deployment_modes_are_reported_without_upstream_or_dem_access(self):
        for enabled, terrain in ((False, False), (True, False), (True, True)):
            with self.subTest(enabled=enabled, terrain=terrain):
                app = create_app()
                app.state.custom_runtime = CustomRuntime(
                    CustomSettings(
                        enabled=enabled,
                        terrain_enabled=terrain,
                        dem_directory=Path("/missing/private-dem-directory"),
                    )
                )
                with (
                    patch(
                        "lunarwindow.ephemeris.horizons.urlopen",
                        side_effect=AssertionError("No upstream"),
                    ),
                    patch("pathlib.Path.open", side_effect=AssertionError("No data reads")),
                    TestClient(app) as client,
                ):
                    response = client.get("/api/capabilities")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertEqual(
                    response.json(),
                    {
                        "schemaVersion": "lunarwindow.capabilities.v1",
                        "customEvaluation": {"enabled": enabled, "terrainEnabled": terrain},
                    },
                )

    def test_uses_startup_configuration_instead_of_changing_environment(self):
        with patch.dict(
            "os.environ",
            {"LUNARWINDOW_CUSTOM_ENABLED": "true", "LUNARWINDOW_CUSTOM_TERRAIN_ENABLED": "false"},
        ):
            enabled_app = create_app()
        with patch.dict(
            "os.environ",
            {"LUNARWINDOW_CUSTOM_ENABLED": "false", "LUNARWINDOW_CUSTOM_TERRAIN_ENABLED": "false"},
        ):
            disabled_app = create_app()
            with TestClient(enabled_app) as first, TestClient(disabled_app) as second:
                self.assertTrue(
                    first.get("/api/capabilities").json()["customEvaluation"]["enabled"]
                )
                self.assertFalse(
                    second.get("/api/capabilities").json()["customEvaluation"]["enabled"]
                )


if __name__ == "__main__":
    unittest.main()
