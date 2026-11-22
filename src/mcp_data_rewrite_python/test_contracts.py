class TestContracts:
    def test_decimal_to_float(self):
            from decimal import Decimal
            from .contracts import jsonable
            assert jsonable({"salary": Decimal("20000.50")}) == {"salary": 20000.5}


    def test_nested(self):
        from decimal import Decimal
        from .contracts import jsonable
        got = jsonable([{"a": Decimal("1.5")}, (Decimal("2"),)])
        assert got == [{"a": 1.5}, [2.0]]


    def test_datetime(self):
        from datetime import datetime
        from .contracts import jsonable
        assert jsonable(datetime(2026, 1, 1, 12, 0)) == "2026-01-01T12:00:00"