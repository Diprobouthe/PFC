from django import template

register = template.Library()

@register.filter
def lookup(dictionary, key):
    """Template filter to lookup dictionary values by key"""
    if isinstance(dictionary, dict):
        return dictionary.get(key, '')
    return ''

@register.filter
def add(value, arg):
    """Template filter to add two values"""
    try:
        return value + arg
    except (ValueError, TypeError):
        return ''

