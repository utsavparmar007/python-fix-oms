import unittest
from unittest.mock import MagicMock
from app.services.order_service import OrderService
from app.models.order import Order

class TestOrderService(unittest.TestCase):
    def setUp(self):
        # mock the repository so we don't need a real database for testing
        self.service = OrderService()
        self.service.repo = MagicMock()
        self.service.position_service = MagicMock()

    def test_full_fill_logic(self):
        """Test if a full fill correctly sets status to FILLED and leaves_qty to 0"""
        # 1. Setup a fake order
        mock_order = Order(
            cl_ord_id="test_123",
            symbol="AAPL",
            quantity=100,
            price=150.0,
            leaves_qty=100,
            cum_qty=0,
            status="NEW",
            side=1
        )
        self.service.repo.get.return_value = mock_order

        # 2. Execute the fill
        result = self.service.fill_order("test_123", "CLIENT")

        # 3. Assertions (The Verification)
        self.assertEqual(result.status, "FILLED")
        self.assertEqual(result.leaves_qty, 0)
        self.assertEqual(result.cum_qty, 100)
        self.service.position_service.update_position.assert_called_once()

    def test_cancel_already_filled_order(self):
        """Test that you CANNOT cancel an order that is already FILLED"""
        mock_order = Order(cl_ord_id="test_456", status="FILLED")
        self.service.repo.get.return_value = mock_order

        
        result = self.service.cancel_order("test_456")
        self.assertIsNone(result)

if __name__ == "__main__":
    unittest.main()