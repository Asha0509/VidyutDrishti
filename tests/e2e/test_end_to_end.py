"""End-to-end test for VidyutDrishti.

Validates the complete system flow:
1. Verify Docker Compose configuration
2. Test detection pipeline integration
3. Test API structure
4. Validate all modules import correctly

Run with:
    python tests/e2e/test_end_to_end.py
"""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

# Add paths
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "backend"))

from app.detection.layer1_zscore import ZScoreAnalyzer
from app.inspection.queue import InspectionQueue


class TestEndToEndFlow(unittest.TestCase):
    """Complete system flow validation."""

    def test_data_ingestion_components(self) -> None:
        """E2E: Verify ingestion components import correctly."""
        from app.ingestion.loader import load_meter_readings
        from app.ingestion.quality import apply_quality_gate
        from app.ingestion.readers import CSVReader

        # Verify components available
        self.assertTrue(callable(CSVReader))
        self.assertTrue(callable(apply_quality_gate))
        self.assertTrue(callable(load_meter_readings))

    def test_detection_pipeline(self) -> None:
        """E2E: Sample data → Z-score detection → Results."""
        import pandas as pd

        # Create sample meter data
        meter_data = pd.DataFrame({
            "meter_id": ["M001"] * 20,
            "date": pd.date_range("2024-01-01", periods=20, freq="D"),
            "kwh": [100.0] * 15 + [50.0] * 5,  # Drop in last 5 days
        })

        # Create topology
        topology = pd.DataFrame({
            "meter_id": ["M001"],
            "dt_id": ["DT001"],
            "feeder_id": ["F001"],
        })

        # Run detection
        analyzer = ZScoreAnalyzer(lookback_days=14)
        results = analyzer.analyze_batch(meter_data, topology, target_date=date(2024, 1, 20))

        # Verify detection ran
        self.assertIsInstance(results, list)

    def test_inspection_queue_generation(self) -> None:
        """E2E: Detection results → Queue generation."""
        import pandas as pd

        # Mock detection results
        detection_df = pd.DataFrame({
            "meter_id": ["M001", "M002"],
            "dt_id": ["DT001", "DT001"],
            "feeder_id": ["F001", "F001"],
            "date": [date(2024, 1, 15), date(2024, 1, 15)],
            "kwh": [50.0, 100.0],
            "confidence": [0.85, 0.3],
            "is_anomaly": [True, False],
            "anomaly_type": ["sudden_drop", "normal"],
            "description": ["40% drop", "Normal consumption"],
        })

        leakage_df = pd.DataFrame({
            "meter_id": ["M001", "M002"],
            "estimated_inr_lost": [1000.0, 0.0],
        })

        topology_df = pd.DataFrame({
            "meter_id": ["M001", "M002"],
            "dt_id": ["DT001", "DT001"],
            "feeder_id": ["F001", "F001"],
            "zone": ["ZoneA", "ZoneA"],
        })

        # Generate queue
        queue = InspectionQueue(max_queue_size=10)
        items = queue.generate(detection_df, leakage_df, topology_df, date(2024, 1, 15))

        # Verify queue generated (only M001 qualifies)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].meter_id, "M001")

    def test_detection_layers_consistency(self) -> None:
        """E2E: All detection layers produce consistent output format."""
        from app.detection import (
            BalanceAnalyzer,
            PeerAnalyzer,
            ZScoreAnalyzer,
        )

        # Verify all analyzers have required methods
        analyzers = [
            BalanceAnalyzer(),
            ZScoreAnalyzer(),
            PeerAnalyzer(),
        ]

        for analyzer in analyzers:
            self.assertTrue(hasattr(analyzer, 'analyze'))
            self.assertTrue(hasattr(analyzer, 'analyze_batch'))


class TestDockerComposeConfig(unittest.TestCase):
    """Docker Compose configuration validation."""

    def test_compose_file_exists(self) -> None:
        """docker-compose.yml present in repo root."""
        compose_file = REPO / "docker-compose.yml"
        self.assertTrue(compose_file.exists(), "docker-compose.yml not found")

    def test_backend_dockerfile_exists(self) -> None:
        """Backend Dockerfile present in infra directory."""
        dockerfile = REPO / "infra" / "Dockerfile.backend"
        self.assertTrue(dockerfile.exists(), "Backend Dockerfile not found")


class TestSystemIntegration(unittest.TestCase):
    """Integration tests across modules."""

    def test_all_detection_layers_importable(self) -> None:
        """All detection modules can be imported."""
        from app.detection import (
            BalanceAnalyzer,
            PeerAnalyzer,
            ZScoreAnalyzer,
        )

        # Verify all exports work
        self.assertTrue(callable(BalanceAnalyzer))
        self.assertTrue(callable(ZScoreAnalyzer))
        self.assertTrue(callable(PeerAnalyzer))

    def test_evaluation_pipeline(self) -> None:
        """Evaluation harness can evaluate mock results."""
        from app.evaluation.harness import (
            DetectionPrediction,
            EvaluationHarness,
            GroundTruthLabel,
        )

        harness = EvaluationHarness()

        ground_truth = [
            GroundTruthLabel("M1", date(2024, 1, 15), True, "theft"),
            GroundTruthLabel("M2", date(2024, 1, 15), False, "normal"),
        ]

        predictions = [
            DetectionPrediction("M1", date(2024, 1, 15), 0.85, True),
            DetectionPrediction("M2", date(2024, 1, 15), 0.2, False),
        ]

        result = harness.evaluate(ground_truth, predictions, "integration_test")

        self.assertEqual(result.metrics.accuracy, 1.0)
        self.assertEqual(result.metrics.true_positives, 1)
        self.assertEqual(result.metrics.true_negatives, 1)


if __name__ == "__main__":
    unittest.main()
