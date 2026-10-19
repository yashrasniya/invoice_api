import re


def unique_username(User, email, fallback='user'):
    """A free username derived from the email's local part (letters, digits and @.+-_ only, <=140 chars)."""
    base = re.sub(r'[^\w.@+-]', '', (email or '').split('@')[0])[:140] or fallback
    username, i = base, 0
    while User.objects.filter(username__iexact=username).exists():
        i += 1
        username = f"{base}{i}"
    return username
