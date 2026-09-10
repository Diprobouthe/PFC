from decimal import Decimal, InvalidOperation

from django import template


register = template.Library()


@register.filter
def percentage_of(value, total):
    """Return a one-decimal percentage for read-only Practice template display."""
    try:
        numerator = Decimal(str(value or 0))
        denominator = Decimal(str(total or 0))
        if denominator <= 0:
            return "0.0"
        return f"{(numerator / denominator * Decimal('100')):.1f}"
    except (InvalidOperation, TypeError, ValueError):
        return "0.0"
