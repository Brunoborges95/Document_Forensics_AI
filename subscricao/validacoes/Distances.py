import json
import unidecode
from thefuzz import fuzz
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize
from jellyfish import _jellyfish as jellyfish
import nltk 

class distances:
    

    def __init__(self, s1, s2):
        self.s1 = s1
        self.s2 = s2
        
        nltk.data.path.append("/opt/nltk_data")

        self.stop_words = set(stopwords.words("portuguese"))
        
        self.normalized_s1 = unidecode.unidecode(s1).lower()
        self.normalized_s2 = unidecode.unidecode(s2).lower()
            
    
    def jaro_winkler_similarity(self):
        return 100 * jellyfish.jaro_winkler_similarity(
            self.normalized_s1, self.normalized_s2
        )
    
    def find_abbreviation_match(self):
        normalized_s1_tokens = [
            word
            for word in word_tokenize(self.normalized_s1)
            if word not in self.stop_words
        ]
        normalized_s2_tokens = [
            word
            for word in word_tokenize(self.normalized_s2)
            if word not in self.stop_words
        ]

        s1_abbreviation = [token[0] for token in normalized_s1_tokens]
        s2_abbreviation = [token[0] for token in normalized_s2_tokens]
        score = fuzz.ratio(
                " ".join(s1_abbreviation), " ".join(s2_abbreviation))

        return score

    def norm_score(self, jw_weight=1, ab_weight=0.2):
        jw_score = self.jaro_winkler_similarity()
        ab_score = self.find_abbreviation_match()
        if jw_score == 0 or ab_score == 0:
            return 0
        jw_score = (jw_score - 50) * 2
        return (jw_weight * jw_score + ab_score * ab_weight) / (jw_weight + ab_weight)