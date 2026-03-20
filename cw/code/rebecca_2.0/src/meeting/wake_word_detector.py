"""
Wake word detector for voice command recognition.

Handles detection of wake words with fuzzy matching to
account for ASR (Automatic Speech Recognition) errors.
"""

from typing import Tuple


class WakeWordDetector:
    """
    Detect wake words in transcribed speech.

    Uses multi-layer matching:
    1. Exact variant matching (fastest)
    2. Fuzzy phonetic matching via Soundex
    3. Edit distance matching via Levenshtein

    This catches ASR misrecognitions like "queba", "qaba", "kuba", etc.
    """

    # Exact wake word variants (checked first)
    WAKE_WORD_VARIANTS = [
        'qa bot', 'qabot', 'q a bot', 'q.a. bot',
        'qa about',  # Very common misrecognition
        'qava', 'queba', 'qaba',  # Common misrecognitions
        'cue a bot', 'queue a bot', 'qa bought',
        'qa bott', 'qa butt', 'qa but',
        'hey qa bot', 'hey qabot',
        'q about', 'cube a bot', 'q a bought',
    ]

    # Primary wake word for fuzzy matching
    WAKE_WORD_PRIMARY = 'qabot'

    # Minimum query length after wake word
    MIN_QUERY_LENGTH = 3

    def __init__(self, bot_name: str = "QA Bot"):
        """
        Initialize wake word detector.

        Args:
            bot_name: Bot name to ignore in speaker filtering
        """
        self.bot_name = bot_name

    @staticmethod
    def soundex(word: str) -> str:
        """
        Generate Soundex code for a word.

        Soundex encodes words by their phonetic sound, making it
        useful for catching ASR misrecognitions.

        Args:
            word: Word to encode

        Returns:
            4-character Soundex code
        """
        if not word:
            return "0000"

        word = word.upper()

        # Keep first letter
        soundex = word[0]

        # Mapping for consonants
        mapping = {
            'B': '1', 'F': '1', 'P': '1', 'V': '1',
            'C': '2', 'G': '2', 'J': '2', 'K': '2', 'Q': '2', 'S': '2', 'X': '2', 'Z': '2',
            'D': '3', 'T': '3',
            'L': '4',
            'M': '5', 'N': '5',
            'R': '6'
        }

        prev_code = mapping.get(word[0], '0')

        for char in word[1:]:
            code = mapping.get(char, '0')
            if code != '0' and code != prev_code:
                soundex += code
                if len(soundex) == 4:
                    break
            prev_code = code

        # Pad with zeros
        return soundex.ljust(4, '0')[:4]

    @staticmethod
    def levenshtein_distance(s1: str, s2: str) -> int:
        """
        Calculate Levenshtein (edit) distance between two strings.

        Args:
            s1: First string
            s2: Second string

        Returns:
            Number of edits needed to transform s1 to s2
        """
        if len(s1) < len(s2):
            return WakeWordDetector.levenshtein_distance(s2, s1)

        if len(s2) == 0:
            return len(s1)

        previous_row = range(len(s2) + 1)

        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row

        return previous_row[-1]

    def fuzzy_match(self, word: str) -> bool:
        """
        Check if a word fuzzy-matches the wake word using phonetic matching.

        Uses both Soundex (phonetic) and Levenshtein (edit distance) matching
        to catch ASR misrecognitions like "queba", "qaba", "kuba", etc.

        Args:
            word: Word to check (should be stripped of punctuation)

        Returns:
            True if word is likely a wake word variant
        """
        word_clean = word.lower().strip()

        # Skip very short or very long words
        if len(word_clean) < 3 or len(word_clean) > 10:
            return False

        # Check Levenshtein distance (allow 2 edits for short words)
        distance = self.levenshtein_distance(word_clean, self.WAKE_WORD_PRIMARY)
        if distance <= 2:
            return True

        # Check Soundex match
        word_soundex = self.soundex(word_clean)
        primary_soundex = self.soundex(self.WAKE_WORD_PRIMARY)
        if word_soundex == primary_soundex:
            return True

        return False

    def detect(self, text: str, speaker: str) -> Tuple[bool, str]:
        """
        Detect wake word in transcribed text and extract query.

        Uses multi-layer matching:
        1. Exact variant matching (fastest)
        2. Fuzzy phonetic matching (catches new ASR errors)

        Args:
            text: Transcribed text
            speaker: Speaker name

        Returns:
            Tuple of (detected, extracted_query)
        """
        # Ignore bot's own speech to prevent feedback loops
        speaker_lower = speaker.lower()
        if speaker_lower in ['qa bot', 'qabot', self.bot_name.lower()]:
            return False, ""

        text_lower = text.lower()

        # Layer 1: Check exact variants (fastest path)
        detected_variant = None
        for variant in self.WAKE_WORD_VARIANTS:
            if variant in text_lower:
                detected_variant = variant
                break

        # Layer 2: Fuzzy phonetic matching for first word(s)
        if not detected_variant:
            # Extract first 1-2 words to check
            words = text_lower.replace(',', ' ').replace('.', ' ').split()
            if words:
                # Check first word
                if self.fuzzy_match(words[0]):
                    detected_variant = words[0]
                # Check first two words combined (e.g., "cue a" -> "qa")
                elif len(words) >= 2:
                    combined = words[0] + words[1]
                    if self.fuzzy_match(combined):
                        detected_variant = f"{words[0]} {words[1]}"

        if not detected_variant:
            return False, ""

        # Extract query after wake word
        parts = text_lower.split(detected_variant, 1)
        query = parts[1].strip(' ,!?:') if len(parts) > 1 else ""

        # Need actual question/command (at least a few characters)
        if not query or len(query) < self.MIN_QUERY_LENGTH:
            return False, ""

        return True, query

    def is_bot_speaker(self, speaker: str) -> bool:
        """
        Check if the speaker is the bot itself.

        Args:
            speaker: Speaker name

        Returns:
            True if speaker is the bot
        """
        speaker_lower = speaker.lower()
        return speaker_lower in ['qa bot', 'qabot', self.bot_name.lower()]
