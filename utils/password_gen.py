"""Secure auto-generated passwords for students imported via Excel."""
import secrets
import string

# Unambiguous character set (no 0/O, 1/l/I confusion)
_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"
_SYMBOLS = "!@#$%"


def generate_secure_password(length: int = 10) -> str:
    """Generate a random, secure, easy-to-type password.

    Guarantees at least one uppercase letter, one lowercase letter,
    one digit and one symbol, then fills the rest randomly and shuffles.
    """
    if length < 6:
        length = 6

    upper = secrets.choice(string.ascii_uppercase.replace("O", "").replace("I", ""))
    lower = secrets.choice(string.ascii_lowercase.replace("l", ""))
    digit = secrets.choice("23456789")
    symbol = secrets.choice(_SYMBOLS)

    remaining_len = length - 4
    remaining = [secrets.choice(_CHARS) for _ in range(remaining_len)]

    password_chars = [upper, lower, digit, symbol] + remaining
    secrets.SystemRandom().shuffle(password_chars)
    return "".join(password_chars)


def generate_unique_username(reg_number: str) -> str:
    """Student username = their register number, normalized (no spaces, uppercase)."""
    return reg_number.strip().upper().replace(" ", "")
