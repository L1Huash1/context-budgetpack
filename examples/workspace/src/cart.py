"""Small synthetic shopping-cart functions."""


def subtotal(prices):
    """Return the sum of item prices."""
    return sum(prices)


def member_total(prices):
    return subtotal(prices) * 0.9


def label(item_count):
    return f"{item_count} items"
