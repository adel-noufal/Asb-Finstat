"""Adel's v2 translation engine, moved into the application pipeline.

Google Translate with MyMemory fallback, byte-limited chunks and Arabic
normalization. Language detection is owned by language_check.py.
"""
from __future__ import annotations

import logging
import random
import re
import time
import unicodedata
from typing import Optional

from deep_translator import GoogleTranslator, MyMemoryTranslator

logger = logging.getLogger(__name__)

DEFAULT_TRANSLATE_BATCH_SIZE = 500  # kept for CLI arg name compatibility
DEFAULT_TRANSLATE_BYTE_LIMIT = 350  # actual limit used internally (bytes)
TRANSLATE_MAX_RETRIES = 5
TRANSLATE_CHUNK_DELAY_SECONDS = 0.4
TRANSLATE_PAGE_DELAY_SECONDS = 1.0
TRANSLATION_DISCLAIMER = (
    "Machine-translated via Google Translate (deep-translator). Review by a "
    "qualified human translator is recommended for legal, medical, or other "
    "high-stakes content."
)

LANGUAGE_NAMES: dict[str, str] = {
    "af": "Afrikaans", "ar": "Arabic", "bg": "Bulgarian", "bn": "Bengali",
    "ca": "Catalan", "cs": "Czech", "cy": "Welsh", "da": "Danish",
    "de": "German", "el": "Greek", "en": "English", "es": "Spanish",
    "et": "Estonian", "fa": "Persian", "fi": "Finnish", "fr": "French",
    "gu": "Gujarati", "he": "Hebrew", "hi": "Hindi", "hr": "Croatian",
    "hu": "Hungarian", "id": "Indonesian", "it": "Italian", "ja": "Japanese",
    "kn": "Kannada", "ko": "Korean", "lt": "Lithuanian", "lv": "Latvian",
    "mk": "Macedonian", "ml": "Malayalam", "mr": "Marathi", "ne": "Nepali",
    "nl": "Dutch", "no": "Norwegian", "pa": "Punjabi", "pl": "Polish",
    "pt": "Portuguese", "ro": "Romanian", "ru": "Russian", "sk": "Slovak",
    "sl": "Slovenian", "so": "Somali", "sq": "Albanian", "sv": "Swedish",
    "sw": "Swahili", "ta": "Tamil", "te": "Telugu", "th": "Thai",
    "tl": "Filipino", "tr": "Turkish", "uk": "Ukrainian", "ur": "Urdu",
    "vi": "Vietnamese", "zh-cn": "Chinese (Simplified)",
    "zh-tw": "Chinese (Traditional)",
}


def _split_translation_chunks(
    text: str,
    byte_limit: int = DEFAULT_TRANSLATE_BYTE_LIMIT,
) -> list[str]:
    """Split text into chunks whose UTF-8 byte length is within byte_limit.

    Chunking by bytes (not characters) ensures every script — Arabic, CJK,
    Cyrillic, Hebrew, Thai, etc. — stays within Google Translate's URL limit,
    because non-Latin characters encode to 2-3× more bytes than characters.
    Natural paragraph / sentence boundaries are preferred so that the
    translator receives grammatically coherent input.
    """
    if len(text.encode("utf-8")) <= byte_limit:
        return [text]

    pieces = re.split(r"(\n\s*\n|(?<=[.!?])\s+)", text)
    chunks: list[str] = []
    current = ""
    current_bytes = 0

    for piece in pieces:
        if not piece:
            continue
        piece_bytes = len(piece.encode("utf-8"))
        # If a single piece exceeds the budget, split it character by character.
        while piece_bytes > byte_limit:
            if current:
                chunks.append(current)
                current = ""
                current_bytes = 0
            # Build the largest safe sub-piece.
            sub = ""
            sub_bytes = 0
            for char in piece:
                char_bytes = len(char.encode("utf-8"))
                if sub_bytes + char_bytes > byte_limit:
                    chunks.append(sub)
                    sub = char
                    sub_bytes = char_bytes
                else:
                    sub += char
                    sub_bytes += char_bytes
            piece = sub
            piece_bytes = sub_bytes

        if current_bytes + piece_bytes <= byte_limit:
            current += piece
            current_bytes += piece_bytes
        else:
            if current:
                chunks.append(current)
            current = piece
            current_bytes = piece_bytes

    if current:
        chunks.append(current)
    return chunks


def _to_google_source_language(source_lang: str) -> str:
    """Map langdetect variants to Google Translate source language codes."""
    language_map = {"zh-cn": "zh-CN", "zh-tw": "zh-TW"}
    return language_map.get(source_lang.lower(), source_lang.lower())


def _to_mymemory_source_language(source_lang: str) -> str:
    """Map language codes to the locale codes required by MyMemory."""
    language_map = {
        "ar": "ar-SA", "bn": "bn-IN", "de": "de-DE", "el": "el-GR",
        "en": "en-US", "es": "es-ES", "fa": "fa-IR", "fi": "fi-FI",
        "fr": "fr-FR", "he": "he-IL", "hi": "hi-IN", "id": "id-ID",
        "it": "it-IT", "ja": "ja-JP", "ko": "ko-KR", "nl": "nl-NL",
        "pl": "pl-PL", "pt": "pt-PT", "ro": "ro-RO", "ru": "ru-RU",
        "sv": "sv-SE", "ta": "ta-IN", "te": "te-IN", "th": "th-TH",
        "tr": "tr-TR", "uk": "uk-UA", "ur": "ur-PK", "vi": "vi-VN",
        "zh-cn": "zh-CN", "zh-tw": "zh-TW",
    }
    return language_map.get(source_lang.lower(), source_lang.lower())


_LTR_TRANSLATION_TOKEN_RE = re.compile(
    r"\[[^\]\n]*\]|[A-Za-z0-9][A-Za-z0-9&._:/+()\-]*"
)


def _normalize_arabic_for_translation(text: str) -> str:
    """Normalize PDF Arabic presentation forms and restore visual-order lines."""
    if not any(0xFB50 <= ord(char) <= 0xFEFF for char in text):
        return text

    normalized_lines: list[str] = []
    for line in text.splitlines(keepends=True):
        line_ending = ""
        content = line
        if content.endswith("\r\n"):
            content, line_ending = content[:-2], "\r\n"
        elif content.endswith("\n") or content.endswith("\r"):
            content, line_ending = content[:-1], content[-1]

        protected_tokens: list[str] = []

        def protect_ltr_token(match: re.Match[str]) -> str:
            protected_tokens.append(match.group(0))
            return chr(0xE000 + len(protected_tokens) - 1)

        protected_line = _LTR_TRANSLATION_TOKEN_RE.sub(protect_ltr_token, content)
        logical_line = unicodedata.normalize("NFKC", protected_line)[::-1]
        for token_index, token in enumerate(protected_tokens):
            logical_line = logical_line.replace(chr(0xE000 + token_index), token)
        normalized_lines.append(logical_line + line_ending)

    logger.info("Normalized visual-order Arabic PDF text before translation.")
    return "".join(normalized_lines)


def _normalize_text_for_translation(text: str, source_lang: str) -> str:
    """Strip control characters/NUL bytes and normalize Unicode compatibility glyphs."""
    # Always strip NUL bytes and unprintable control characters to prevent API errors
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    if source_lang == "ar":
        text = _normalize_arabic_for_translation(text)

    normalized_text = unicodedata.normalize("NFKC", text)
    if normalized_text != text:
        logger.info("Normalized Unicode compatibility glyphs before translation.")
    return normalized_text.replace("\x00", "")


# MyMemory enforces a hard character limit; stay well within it.
_MYMEMORY_MAX_CHARS = 450


def _translate_chunk_with_retry(
    chunk: str,
    chunk_index: int,
    translator: "GoogleTranslator",
    fallback_translator: "Optional[MyMemoryTranslator]",
    *,
    _depth: int = 0,
) -> Optional[str]:
    """Translate one chunk with retries, half-splitting on TranslationNotFound.

    Returns the translated string, or None if all strategies are exhausted
    (caller is responsible for keeping the original text in that case).
    """
    for attempt_index in range(TRANSLATE_MAX_RETRIES):
        attempt_number = attempt_index + 1
        try:
            result = translator.translate(chunk)
            if result is not None:
                return result
            if _depth == 0:
                logger.warning(
                    "Google Translate returned no translation for chunk %d on attempt %d/%d.",
                    chunk_index, attempt_number, TRANSLATE_MAX_RETRIES,
                )
        except Exception as exc:
            error_type = type(exc).__name__
            log_fn = logger.warning if _depth == 0 else logger.debug
            log_fn(
                "Google Translate failed for chunk %d on attempt %d/%d: %s",
                chunk_index, attempt_number, TRANSLATE_MAX_RETRIES, error_type,
            )
            if error_type == "TranslationNotFound" and _depth < 3 and len(chunk) > 1:
                # Split the chunk in half and retry each half independently.
                mid = len(chunk) // 2
                left = _translate_chunk_with_retry(
                    chunk[:mid], chunk_index, translator, fallback_translator,
                    _depth=_depth + 1,
                )
                time.sleep(0.5)
                right = _translate_chunk_with_retry(
                    chunk[mid:], chunk_index, translator, fallback_translator,
                    _depth=_depth + 1,
                )
                if left is not None or right is not None:
                    return (left or chunk[:mid]) + (right or chunk[mid:])
                # Both halves failed — fall through to MyMemory below.
                break

        if attempt_number < TRANSLATE_MAX_RETRIES:
            # Exponential backoff with jitter before the next attempt.
            time.sleep((2 ** attempt_number) + random.random())

    # --- MyMemory fallback ---
    if fallback_translator is not None:
        # MyMemory enforces a hard character limit; split if needed.
        if len(chunk) <= _MYMEMORY_MAX_CHARS:
            sub_chunks = [chunk]
        else:
            sub_chunks = [
                chunk[i: i + _MYMEMORY_MAX_CHARS]
                for i in range(0, len(chunk), _MYMEMORY_MAX_CHARS)
            ]
        results: list[str] = []
        all_ok = True
        for sub in sub_chunks:
            try:
                sub_result = fallback_translator.translate(sub)
                if sub_result is not None:
                    results.append(sub_result)
                    continue
            except Exception as fallback_exc:
                logger.warning(
                    "MyMemory fallback failed for chunk %d: %s",
                    chunk_index, type(fallback_exc).__name__,
                )
            results.append(sub)
            all_ok = False
        translated = "".join(results)
        if all_ok:
            logger.info(
                "Google Translate exhausted retries for chunk %d; used MyMemory fallback.",
                chunk_index,
            )
        return translated

    logger.warning(
        "Could not translate chunk %d after %d attempts; keeping original text.",
        chunk_index, TRANSLATE_MAX_RETRIES,
    )
    return None


def translate_to_english(
    text: str,
    source_lang: str,
    batch_size: int = DEFAULT_TRANSLATE_BATCH_SIZE,
) -> Optional[str]:
    """Translate text to English, retaining failed chunks in their original form."""
    if source_lang == "en":
        return text
    if source_lang == "unknown":
        logger.warning("Translation skipped: source language is unknown.")
        return None

    text = _normalize_text_for_translation(text, source_lang)

    try:
        translator = GoogleTranslator(
            source=_to_google_source_language(source_lang),
            target="en",
        )
    except Exception as exc:
        logger.warning(
            "Google Translate translation setup failed: %s",
            type(exc).__name__,
        )
        return None

    try:
        fallback_translator: Optional[MyMemoryTranslator] = MyMemoryTranslator(
            source=_to_mymemory_source_language(source_lang),
            target="en-US",
        )
    except Exception as exc:
        logger.warning("MyMemory fallback unavailable: %s", type(exc).__name__)
        fallback_translator = None

    translated_chunks: list[str] = []
    fallback_chunk_count = 0
    for chunk_index, chunk in enumerate(_split_translation_chunks(text), start=1):
        if chunk_index > 1:
            time.sleep(TRANSLATE_CHUNK_DELAY_SECONDS)

        translated_chunk = _translate_chunk_with_retry(
            chunk, chunk_index, translator, fallback_translator
        )
        if translated_chunk is None:
            translated_chunks.append(chunk)
            fallback_chunk_count += 1
        else:
            translated_chunks.append(translated_chunk)

    if fallback_chunk_count:
        logger.warning(
            "Page text translated with %d/%d chunk(s) kept in original language "
            "due to repeated translation failures.",
            fallback_chunk_count,
            len(translated_chunks),
        )

    return "".join(translated_chunks)


