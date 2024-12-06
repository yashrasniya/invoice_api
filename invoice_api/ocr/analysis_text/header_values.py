
class HeaderValues:
    InvoiceNumber = ["Invoice Number"]
    InvoiceDate = ["Invoice Date"]


import re
from difflib import SequenceMatcher
import unicodedata


def string_matching_techniques(value, string_list):
    """
    Demonstrate multiple string matching techniques
    """
    print("Original Value:", value)

    # 1. Basic Substring Match
    substring_matches = [s for s in string_list if value.lower() in s.lower()]
    print("\n1. Substring Matches:")
    print(substring_matches)

    # 2. Regular Expression Match
    regex_matches = [s for s in string_list if re.search(value, s, re.IGNORECASE)]
    print("\n2. Regex Matches:")
    print(regex_matches)

    # 3. Fuzzy Matching (Similarity Ratio)
    def fuzzy_match(s1, s2, threshold=0.6):
        """Calculate similarity ratio between two strings"""
        return SequenceMatcher(None, s1.lower(), s2.lower()).ratio() >= threshold

    fuzzy_matches = [s for s in string_list if fuzzy_match(value, s)]
    print("\n3. Fuzzy Matches (60% similarity):")
    print(fuzzy_matches)

    # 4. Normalized String Comparison
    def normalize_string(s):
        """Remove accents and normalize string"""
        return unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('utf-8').lower()

    normalized_matches = [s for s in string_list if normalize_string(value) in normalize_string(s)]
    print("\n4. Normalized Matches (handles accents):")
    print(normalized_matches)

    # 5. Levenshtein Distance (edit distance)
    def levenshtein_distance(s1, s2):
        """Calculate the Levenshtein distance between two strings"""
        if len(s1) < len(s2):
            return levenshtein_distance(s2, s1)

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

    def edit_distance_match(s1, s2, max_distance=2):
        """Check if Levenshtein distance is within threshold"""
        return levenshtein_distance(s1.lower(), s2.lower()) <= max_distance

    edit_distance_matches = [s for s in string_list if edit_distance_match(value, s)]
    print("\n5. Edit Distance Matches (max 2 edits):")
    print(edit_distance_matches)


# Example usage
def main():
    # Sample list of strings to match against
    string_list = [
        "Hello World",
        "hello universe",
        "Héllo Wörld",
        "Hi there",
        "Hello Planet",
        "Hallo Welt"
    ]

    # Demonstrate matching techniques
    string_matching_techniques("Hello w", string_list)


if __name__ == "__main__":
    main()


# Advanced Class for Comprehensive String Matching
class StringMatcher:
    @staticmethod
    def match(value, string_list, method='substring', threshold=0.6):
        """
        Flexible string matching method

        Methods:
        - 'substring': Contains substring
        - 'regex': Regular expression match
        - 'fuzzy': Fuzzy matching
        - 'normalized': Normalized string comparison
        - 'edit_distance': Levenshtein distance
        """
        if method == 'substring':
            return [s for s in string_list if value.lower() in s.lower()]

        elif method == 'regex':
            return [s for s in string_list if re.search(value, s, re.IGNORECASE)]

        elif method == 'fuzzy':
            return [s for s in string_list
                    if SequenceMatcher(None, value.lower(), s.lower()).ratio() >= threshold]

        elif method == 'normalized':
            def normalize(s):
                return unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('utf-8').lower()

            return [s for s in string_list if normalize(value) in normalize(s)]

        elif method == 'edit_distance':
            def levenshtein(s1, s2):
                if len(s1) < len(s2):
                    return levenshtein(s2, s1)
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

            return [s for s in string_list if levenshtein(value.lower(), s.lower()) <= threshold]

        else:
            raise ValueError("Invalid matching method")


# Demonstration of the advanced StringMatcher
def advanced_matcher_demo():
    string_list = [
        "Hello World",
        "hello universe",
        "Héllo Wörld",
        "Hi there",
        "Hello Planet",
        "Hallo Welt"
    ]

    print("\nAdvanced String Matcher Demonstrations:")

    # Different matching methods
    print("Substring Match:",
          StringMatcher.match("Hello", string_list, method='substring'))

    print("Fuzzy Match:",
          StringMatcher.match("Hello", string_list, method='fuzzy', threshold=0.6))

    print("Edit Distance Match:",
          StringMatcher.match("Hello", string_list, method='edit_distance', threshold=2))

