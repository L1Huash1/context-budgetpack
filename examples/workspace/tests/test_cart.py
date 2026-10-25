from src.cart import member_total, subtotal


def test_totals():
    assert subtotal([10, 20]) == 30
    assert member_total([10, 20]) == 27
