"""Arabic text reshaping and bidirectional display helper for Tkinter / CustomTkinter."""

def fix_arabic(text: str) -> str:
    if not text:
        return ""
    # Check if text contains any Arabic characters
    if not any("\u0600" <= c <= "\u06ff" or "\u0750" <= c <= "\u077f" or "\ufb50" <= c <= "\ufdff" or "\ufe70" <= c <= "\ufeff" for c in text):
        return text

    try:
        import arabic_reshaper
        from bidi.algorithm import get_display

        # Configuration to avoid breaking digits and latin words
        reshaper = arabic_reshaper.ArabicReshaper(
            configuration={
                "delete_harakat": False,
                "support_ligatures": True,
            }
        )
        reshaped = reshaper.reshape(text)
        return get_display(reshaped)
    except Exception:
        return text
